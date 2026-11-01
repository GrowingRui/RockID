"""Training helpers: metrics, class weights, image prep (numpy), and the TF pipeline/model if TF is installed."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from rockid_ml import metrics, prep
from rockid_ml.images import load_rgb


# ---------------------------------------------------------------- metrics

def test_topk_accuracy():
    scores = np.array([[0.1, 0.7, 0.2], [0.5, 0.3, 0.2], [0.2, 0.3, 0.5]])
    y = np.array([1, 1, 0])
    assert metrics.topk_accuracy(y, scores, 1) == pytest.approx(1 / 3)
    assert metrics.topk_accuracy(y, scores, 2) == pytest.approx(2 / 3)
    assert metrics.topk_accuracy(y, scores, 3) == 1.0


def test_per_class_recall_handles_missing_class():
    r = metrics.per_class_recall(np.array([0, 0, 1, 1]), np.array([0, 1, 1, 1]), ["a", "b", "c"])
    assert r["a"] == 0.5 and r["b"] == 1.0 and np.isnan(r["c"])


def test_class_weights_balance_and_mean_one():
    y = np.array([0] * 80 + [1] * 20)
    w = metrics.class_weights(y, 2, power=1.0)
    assert w[y].mean() == pytest.approx(1.0)
    assert (w[y] * (y == 0)).sum() == pytest.approx((w[y] * (y == 1)).sum())  # equal total weight per class
    assert np.allclose(metrics.class_weights(y, 2, power=0), 1.0)
    with pytest.raises(ValueError):
        metrics.class_weights(y, 3)


# ---------------------------------------------------------------- prep

@pytest.fixture()
def raw(tmp_path):
    rng = np.random.default_rng(1)
    root = tmp_path / "raw"
    (root / "igneous").mkdir(parents=True)
    rows = []
    for i, size in enumerate([(640, 400), (200, 150), (300, 900)]):
        rel = f"igneous/{i}Basalt.png"
        Image.fromarray(rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)).save(root / rel)
        rows.append({"rel_path": rel, "label": "basalt", "pixel_sha256": prep.pixel_sha256(load_rgb(root / rel)),
                     "cluster_id": i, "split": "train"})
    return root, pd.DataFrame(rows)


def test_prepare_images_checks_pixels_and_shrinks(raw, tmp_path):
    root, m = raw
    m.loc[2, "pixel_sha256"] = "0" * 64  # pretend the dataset changed
    out = prep.prepare_images(m, root, tmp_path / "prep", short_side=160, workers=2)
    assert out["sha_ok"].tolist() == [True, True, False]
    sizes = [Image.open(p).size for p in out["prep_path"]]
    assert sizes == [(256, 160), (200, 150), (160, 480)]  # never upscaled, aspect kept
    again = prep.prepare_images(m, root, tmp_path / "prep", short_side=160)
    assert again["sha_ok"].isna().all()  # already prepared: skipped


def test_client_preprocess_center_square(raw):
    root, m = raw
    a = prep.client_preprocess(root / m.loc[0, "rel_path"], size=224)
    assert a.shape == (224, 224, 3) and a.dtype == np.uint8


# ---------------------------------------------------------------- TensorFlow parts

def test_tf_pipeline_and_model(raw, tmp_path):
    tf = pytest.importorskip("tensorflow")
    from rockid_ml import train

    root, m = raw
    out = prep.prepare_images(m, root, tmp_path / "prep", short_side=96)
    cfg = train.TrainConfig(image_size=64, batch_size=2, stage1_epochs=1)
    y = np.array([0, 1, 1])

    tr = train.make_dataset(out["prep_path"], y, 2, cfg, training=True, sample_weight=np.ones(3))
    x, oh, w = next(iter(tr))
    assert x.shape == (2, 64, 64, 3) and oh.shape == (2, 2) and w.shape == (2,)
    assert 0 <= float(tf.reduce_min(x)) and float(tf.reduce_max(x)) <= 255
    steps = train.steps_per_epoch(3, cfg)
    it = iter(tr)
    epoch1 = np.concatenate([next(it)[0].numpy() for _ in range(steps)])
    epoch2 = np.concatenate([next(it)[0].numpy() for _ in range(steps)])
    assert not np.allclose(epoch1[:3], epoch2[:3])  # new order/augmentation each epoch

    va = train.make_dataset(out["prep_path"], y, 2, cfg, training=False)
    v1 = np.concatenate([b[0].numpy() for b in va])
    assert v1.shape == (3, 64, 64, 3)
    assert np.allclose(v1, np.concatenate([b[0].numpy() for b in va]))  # eval is deterministic

    model, base = train.build_model(cfg, 2, weights=None)
    assert model.output_shape == (None, 2)
    frozen = train.count_params(model)["trainable"]
    cut = train.unfreeze_top(base, 0.3)
    assert 0 < cut < len(base.layers)
    assert not any(l.trainable for l in base.layers if isinstance(l, tf.keras.layers.BatchNormalization))
    assert train.count_params(model)["trainable"] > frozen

    train.compile_model(model, 1e-3, cfg)
    h = train.fit_stage(model, tr, va, 1, steps, tmp_path / "run" / "stage1", cfg)
    assert len(h) == 1 and (tmp_path / "run" / "stage1" / "done.json").exists()
    assert len(train.fit_stage(model, tr, va, 1, steps, tmp_path / "run" / "stage1", cfg)) == 1  # finished stage is skipped
    assert train.predict_logits(model, va).shape == (3, 2)


def test_config_roundtrip_and_run_dir_guard(tmp_path):
    pytest.importorskip("tensorflow")
    from rockid_ml import train

    cfg = train.load_config(__import__("pathlib").Path(__file__).parents[1] / "configs" / "train_v1.json")
    assert cfg.crop_aspect == (0.75, 1.333)
    train.prepare_run_dir(tmp_path / "r", cfg)
    train.prepare_run_dir(tmp_path / "r", cfg)  # same config: fine
    other = train.TrainConfig(**{**cfg.to_dict(), "stage2_lr": 1e-4})
    with pytest.raises(RuntimeError, match="stage2_lr"):
        train.prepare_run_dir(tmp_path / "r", other)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"learning_rate": 1}))
    with pytest.raises(ValueError):
        train.load_config(bad)


def test_ensure_extracted_repairs_partial_unzip(tmp_path):
    import zipfile

    zp = tmp_path / "ds.zip"
    names = ["rocks/igneous/1Basalt.png", "rocks/sedimentary/Chert35.png"]
    with zipfile.ZipFile(zp, "w") as z:
        for n in names:
            z.writestr(n, b"x")
    dest = tmp_path / "raw"
    (dest / "rocks" / "igneous").mkdir(parents=True)
    (dest / "rocks" / "igneous" / "1Basalt.png").write_bytes(b"x")  # half-finished earlier unzip

    assert prep.ensure_extracted(zp, dest, names) == []
    assert all((dest / n).exists() for n in names) and not (tmp_path / "raw.partial").exists()
    assert prep.ensure_extracted(zp, dest, names) == []  # complete: nothing to do

    missing = prep.ensure_extracted(zp, dest, names + ["rocks/sedimentary/chert99.png"])
    assert missing == ["rocks/sedimentary/chert99.png"]
    assert "no file with that name" in prep.missing_hints(zp, missing)[0]
    assert "Chert35.png" in prep.missing_hints(zp, ["other/CHERT35.png"])[0]
