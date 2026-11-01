"""Phase 2 training: tf.data pipeline, MobileNet transfer model and two-stage fine-tuning with resume.

The model takes raw RGB in 0–255 (float32) and normalizes in-graph, so clients never re-implement
preprocessing. It outputs **logits**; softmax and the temperature fitted in 03_evaluate are added
at export time."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import tensorflow as tf  # noqa: E402

keras = tf.keras
AUTOTUNE = tf.data.AUTOTUNE


@dataclass
class TrainConfig:
    run_name: str = "mnv2-classes_v1-s42"  # Drive folder under runs/; same name = resume
    split_manifest: str = "splits/split_manifest_classes_v1.csv"  # relative to ml/
    class_file: str = "configs/classes_v1.json"
    seed: int = 42

    arch: str = "mobilenet_v2"  # or "mobilenet_v3_large"
    alpha: float = 1.0
    image_size: int = 224
    prep_short_side: int = 288  # cached JPEGs; leaves room for random crops
    batch_size: int = 32
    dropout: float = 0.3
    label_smoothing: float = 0.1
    class_weight_power: float = 1.0  # 1 = balanced, 0.5 = softened, 0 = off

    # Augmentation. Rocks have no "up", so all flips and 90° turns are fair; hue stays mild (color is diagnostic).
    crop_area_min: float = 0.5
    crop_aspect: tuple[float, float] = (0.75, 1.333)
    flips: bool = True
    rot90: bool = True
    brightness: float = 0.15  # max delta on a 0–1 scale
    contrast: float = 0.15  # factor in [1 - c, 1 + c]
    saturation: float = 0.15
    hue: float = 0.02

    # Stage 1: frozen backbone, train the head
    stage1_epochs: int = 15
    stage1_lr: float = 1e-3
    # Stage 2: unfreeze the top of the backbone (BatchNorm stays frozen)
    unfreeze_frac: float = 0.3
    stage2_epochs: int = 30
    stage2_lr: float = 1e-5
    patience: int = 5
    monitor: str = "val_top1"

    deterministic_ops: bool = False  # bitwise-reproducible but slower; the gate allows ±1.5 points

    # TF.js smoke test: converter installed with --no-deps, so it runs on the training TensorFlow
    tfjs_converter: str = "tensorflowjs==4.22.0"
    tfjs_quantization: str = "float16"  # "float16" | "uint8" | "none"; uint8 is too lossy for MobileNetV2 (ADR 0002)
    tfjs_max_abs_diff: float = 0.02  # probability tolerance vs Keras (Phase 3 limit)
    tfjs_npm: str = "@tensorflow/tfjs@4.22.0"
    max_web_model_mb: float = 5.0

    def to_dict(self) -> dict:
        return asdict(self)


def load_config(path: str | Path) -> TrainConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    known = {f.name for f in fields(TrainConfig)}
    unknown = set(raw) - known - {"_comment"}
    if unknown:
        raise ValueError(f"unknown keys in {path}: {sorted(unknown)}")
    raw = {k: v for k, v in raw.items() if k in known}
    if "crop_aspect" in raw:
        raw["crop_aspect"] = tuple(raw["crop_aspect"])
    return TrainConfig(**raw)


def prepare_run_dir(run_dir: Path, cfg: TrainConfig) -> None:
    """Creates the run folder, or checks that an existing one was started with the same config
    (resuming with different settings would silently mix two experiments)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    f = run_dir / "config.json"
    current = json.loads(json.dumps(cfg.to_dict()))
    if f.exists():
        saved = json.loads(f.read_text())
        diff = sorted(k for k in set(saved) | set(current) if saved.get(k) != current.get(k))
        if diff:
            raise RuntimeError(f"{run_dir} was started with a different config ({', '.join(diff)}). "
                               "Change run_name, or delete that folder to start over.")
    else:
        f.write_text(json.dumps(current, indent=2))


# ---------------------------------------------------------------- data

def _decode(jpeg: tf.Tensor) -> tf.Tensor:
    return tf.io.decode_jpeg(jpeg, channels=3)


def _resize(img: tf.Tensor, size: int) -> tf.Tensor:
    return tf.image.resize(img, (size, size), method="bilinear", antialias=True)


def center_square(img: tf.Tensor) -> tf.Tensor:
    h, w = tf.shape(img)[0], tf.shape(img)[1]
    side = tf.minimum(h, w)
    return tf.image.crop_to_bounding_box(img, (h - side) // 2, (w - side) // 2, side, side)


def augment(img: tf.Tensor, seed: tf.Tensor, cfg: TrainConfig) -> tf.Tensor:
    """uint8 HWC → float32 (size, size, 3) in 0–255. Stateless ops, so a seed fully fixes the result."""
    s = tf.random.experimental.stateless_split(seed, num=8)
    begin, size, _ = tf.image.stateless_sample_distorted_bounding_box(
        tf.shape(img), bounding_boxes=tf.zeros([1, 0, 4]), seed=s[0], min_object_covered=0.0,
        aspect_ratio_range=cfg.crop_aspect, area_range=(cfg.crop_area_min, 1.0),
        max_attempts=20, use_image_if_no_bounding_boxes=True)
    x = _resize(tf.slice(img, begin, size), cfg.image_size)
    if cfg.flips:
        x = tf.image.stateless_random_flip_left_right(x, s[1])
        x = tf.image.stateless_random_flip_up_down(x, s[2])
    if cfg.rot90:
        x = tf.image.rot90(x, tf.random.stateless_uniform([], s[3], 0, 4, dtype=tf.int32))
    x = x / 255.0
    if cfg.brightness:
        x = tf.image.stateless_random_brightness(x, cfg.brightness, s[4])
    if cfg.contrast:
        x = tf.image.stateless_random_contrast(x, 1 - cfg.contrast, 1 + cfg.contrast, s[5])
    if cfg.saturation:
        x = tf.image.stateless_random_saturation(x, 1 - cfg.saturation, 1 + cfg.saturation, s[6])
    if cfg.hue:
        x = tf.image.stateless_random_hue(x, cfg.hue, s[7])
    return tf.clip_by_value(x, 0.0, 1.0) * 255.0


def eval_transform(img: tf.Tensor, cfg: TrainConfig) -> tf.Tensor:
    return _resize(center_square(img), cfg.image_size)


def make_dataset(paths, y, n_classes: int, cfg: TrainConfig, training: bool, sample_weight=None) -> tf.data.Dataset:
    """Training: shuffled, augmented, **repeats forever** (use `steps_per_epoch`), yields (x, onehot, weight).
    One endless iterator is what makes each epoch get a new order and new augmentations: re-iterating a
    seeded dataset would replay the same ones. Eval: in order, one pass, yields (x, onehot).
    Encoded JPEG bytes are cached in memory (~30 KB each); decoding them is cheap."""
    cols = (list(paths), np.asarray(y, np.int32))
    if training:
        cols += (np.asarray(sample_weight, np.float32),)
    ds = tf.data.Dataset.from_tensor_slices(cols)
    ds = ds.map(lambda p, *rest: (tf.io.read_file(p), *rest), num_parallel_calls=AUTOTUNE).cache()

    if training:
        ds = ds.shuffle(len(cols[0]), seed=cfg.seed, reshuffle_each_iteration=True).repeat()
        seeds = tf.data.Dataset.random(seed=cfg.seed).batch(2)
        ds = tf.data.Dataset.zip((ds, seeds)).map(
            lambda e, s: (augment(_decode(e[0]), s, cfg), tf.one_hot(e[1], n_classes), e[2]),
            num_parallel_calls=AUTOTUNE, deterministic=True)
    else:
        ds = ds.map(lambda b, yy: (eval_transform(_decode(b), cfg), tf.one_hot(yy, n_classes)),
                    num_parallel_calls=AUTOTUNE)
    return ds.batch(cfg.batch_size).prefetch(AUTOTUNE)


# ---------------------------------------------------------------- model

def _backbone(cfg: TrainConfig, weights: str | None):
    shape = (cfg.image_size, cfg.image_size, 3)
    if cfg.arch == "mobilenet_v2":
        return keras.applications.MobileNetV2(input_shape=shape, alpha=cfg.alpha, include_top=False, weights=weights)
    if cfg.arch == "mobilenet_v3_large":
        # Our Rescaling layer does the [-1, 1] mapping, so the built-in preprocessing is turned off.
        return keras.applications.MobileNetV3Large(input_shape=shape, alpha=cfg.alpha, include_top=False,
                                                   weights=weights, include_preprocessing=False)
    raise ValueError(f"unknown arch {cfg.arch!r}")


def build_model(cfg: TrainConfig, n_classes: int, weights: str | None = "imagenet"):
    """Returns (model, backbone). Rescaling → backbone (inference-mode BatchNorm) → GAP → Dropout → Dense logits."""
    inp = keras.Input((cfg.image_size, cfg.image_size, 3), dtype="float32", name="image")
    x = keras.layers.Rescaling(1 / 127.5, offset=-1.0, name="normalize")(inp)
    base = _backbone(cfg, weights)
    base.trainable = False
    # training=False keeps BatchNorm statistics frozen even after the backbone is unfrozen.
    x = base(x, training=False)
    x = keras.layers.GlobalAveragePooling2D(name="pool")(x)
    x = keras.layers.Dropout(cfg.dropout, seed=cfg.seed, name="dropout")(x)
    out = keras.layers.Dense(n_classes, name="logits")(x)
    return keras.Model(inp, out, name=f"rockid_{cfg.arch}"), base


def unfreeze_top(base, frac: float) -> int:
    """Makes the top `frac` of backbone layers trainable, except BatchNorm. Returns the first trainable index."""
    base.trainable = True
    cut = int(round(len(base.layers) * (1 - frac)))
    for i, layer in enumerate(base.layers):
        layer.trainable = i >= cut and not isinstance(layer, keras.layers.BatchNormalization)
    return cut


def compile_model(model, lr: float, cfg: TrainConfig) -> None:
    model.compile(
        optimizer=keras.optimizers.Adam(lr),
        loss=keras.losses.CategoricalCrossentropy(from_logits=True, label_smoothing=cfg.label_smoothing),
        metrics=[keras.metrics.CategoricalAccuracy(name="top1"), keras.metrics.TopKCategoricalAccuracy(3, name="top3")],
    )


def count_params(model) -> dict:
    t = sum(int(np.prod(w.shape)) for w in model.trainable_weights)
    n = sum(int(np.prod(w.shape)) for w in model.non_trainable_weights)
    return {"trainable": t, "frozen": n}


# ---------------------------------------------------------------- training with resume

def read_history(log: Path) -> pd.DataFrame:
    if not log.exists() or log.stat().st_size == 0:
        return pd.DataFrame()
    # A disconnect between the CSV write and the backup can repeat an epoch; keep the last copy.
    return pd.read_csv(log).drop_duplicates("epoch", keep="last").reset_index(drop=True)


def steps_per_epoch(n_train: int, cfg: TrainConfig) -> int:
    return -(-n_train // cfg.batch_size)


def fit_stage(model, train_ds, val_ds, epochs: int, steps: int, stage_dir: Path, cfg: TrainConfig) -> pd.DataFrame:
    """One training stage that survives Colab disconnects: BackupAndRestore resumes mid-stage,
    the best weights (by `cfg.monitor`) are kept on Drive, and a finished stage is skipped on re-run."""
    stage_dir.mkdir(parents=True, exist_ok=True)
    log, best, done = stage_dir / "history.csv", stage_dir / "best.weights.h5", stage_dir / "done.json"
    if done.exists():
        model.load_weights(best)
        print(f"{stage_dir.name}: already finished, loaded best weights")
        return read_history(log)

    prev = read_history(log)
    best_so_far = float(prev[cfg.monitor].max()) if len(prev) else None
    callbacks = [
        keras.callbacks.BackupAndRestore(str(stage_dir / "backup")),
        keras.callbacks.CSVLogger(str(log), append=True),
        keras.callbacks.ModelCheckpoint(str(best), monitor=cfg.monitor, mode="max", save_best_only=True,
                                        save_weights_only=True, initial_value_threshold=best_so_far),
        keras.callbacks.EarlyStopping(monitor=cfg.monitor, mode="max", patience=cfg.patience),
    ]
    model.fit(train_ds, validation_data=val_ds, epochs=epochs, steps_per_epoch=steps, callbacks=callbacks, verbose=2)
    model.load_weights(best)
    h = read_history(log)
    i = int(h[cfg.monitor].idxmax())
    done.write_text(json.dumps({"best_epoch": int(h.loc[i, "epoch"]) + 1, cfg.monitor: float(h.loc[i, cfg.monitor]),
                                "epochs_run": len(h)}, indent=2))
    return h


def predict_logits(model, ds: tf.data.Dataset) -> np.ndarray:
    return model.predict(ds.map(lambda x, *_: x), verbose=0)


# ---------------------------------------------------------------- report

def write_report(out: Path, cfg: TrainConfig, info: dict, val: dict, table: pd.DataFrame,
                 confused: pd.DataFrame, figures: dict[str, Path]) -> Path:
    """Markdown training report (no dataset images, safe to commit)."""
    from datetime import datetime, timezone

    from .metrics import GATE
    from .report import md_table, pct

    def row(name, value, target):
        return f"| {name} | {pct(value)} | ≥ {pct(target)} | {'yes' if value >= target else 'no'} |"

    lines = [
        f"# RockID training run `{cfg.run_name}`", "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "",
        "## Summary", "", *[f"- **{k}:** {v}" for k, v in info.items()], "",
        "## Validation (indicative)", "",
        "The best epoch was picked on validation, so these numbers lean optimistic. "
        "The gate itself is checked on the test and field sets in `03_evaluate`.", "",
        "| metric | val | gate target | met on val |", "|---|---|---|---|",
        row("top-1", val["top1"], GATE["top1"]), row("top-3", val["top3"], GATE["top3"]),
        row(f"lowest class recall ({val['min_recall_class']})", val["min_recall"], GATE["min_recall"]), "",
    ]
    lines += [f"![{k}]({p.parent.name}/{p.name})" for k, p in figures.items()]
    lines += ["", "## Per-class validation recall", "", md_table(table), "",
              "## Most confused pairs (validation)", "", md_table(confused, index=False) if len(confused) else "none", "",
              "## Config", "", "```json", json.dumps(cfg.to_dict(), indent=2), "```", ""]
    path = out / "train.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# Two-series pair that passes the colorblind-separation check (the audit's brown/red pair does not).
TRAIN_COLOR, VAL_COLOR = "#2a78d6", "#eb6834"


def plot_history(histories: dict[str, pd.DataFrame], path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4))
    offset = 0
    for stage, h in histories.items():
        if h.empty:
            continue
        ep = np.arange(len(h)) + offset + 1
        for ax, m in zip(axes, ("loss", "top1")):
            ax.plot(ep, h[m], color=TRAIN_COLOR, lw=2, ls="--" if stage == "stage2" else "-")
            ax.plot(ep, h[f"val_{m}"], color=VAL_COLOR, lw=2, ls="--" if stage == "stage2" else "-")
        if offset:  # divider where stage 2 starts
            for ax in axes:
                ax.axvline(offset + 0.5, color="#d9cfc3", lw=1)
        offset += len(h)
    for ax, m in zip(axes, ("loss", "top-1 accuracy")):
        ax.set_xlabel("epoch (dashed = stage 2)")
        ax.set_ylabel(m)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].legend(["train", "val"], frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
