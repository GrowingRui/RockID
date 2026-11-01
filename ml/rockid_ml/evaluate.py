"""Phase 2 evaluation: calibration, "uncertain" thresholds, test/field metrics and the go/no-go gate.

Everything that is *fitted* (temperature, thresholds) uses validation only; test and field sets are
only scored. Numpy/scipy only, so it is unit-tested without TensorFlow."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import minimize_scalar  # noqa: E402

from .dedup import hamming_pairs, phash_to_uint64  # noqa: E402
from .metrics import GATE, per_class_recall, topk_accuracy  # noqa: E402
from .report import md_table, pct  # noqa: E402

# Chart colors: validated two-series pair, a recessive reference gray, and a one-hue sequential ramp.
BLUE, ORANGE, REF_GRAY = "#2a78d6", "#eb6834", "#9a9a94"
SEQ_BLUES = ["#ffffff", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


# ---------------------------------------------------------------- calibration

def softmax(z: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    z = np.asarray(z, dtype=np.float64) / temperature
    e = np.exp(z - z.max(1, keepdims=True))
    return e / e.sum(1, keepdims=True)


def nll(logits: np.ndarray, y: np.ndarray, temperature: float = 1.0) -> float:
    p = softmax(logits, temperature)
    return float(-np.log(np.clip(p[np.arange(len(y)), y], 1e-12, None)).mean())


def fit_temperature(logits: np.ndarray, y: np.ndarray) -> float:
    """Temperature T > 0 minimizing validation NLL of softmax(logits / T). Doesn't change any prediction."""
    r = minimize_scalar(lambda t: nll(logits, y, np.exp(t)), bounds=(np.log(0.05), np.log(20)), method="bounded")
    return float(np.exp(r.x))


def ece(probs: np.ndarray, y: np.ndarray, n_bins: int = 15) -> float:
    """Expected calibration error of the top-1 confidence (0 = perfectly calibrated)."""
    conf, correct = probs.max(1), probs.argmax(1) == y
    bins = np.minimum((conf * n_bins).astype(int), n_bins - 1)
    return float(sum(abs(correct[bins == b].mean() - conf[bins == b].mean()) * (bins == b).mean()
                     for b in range(n_bins) if (bins == b).any()))


def reliability(probs: np.ndarray, y: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    conf, correct = probs.max(1), probs.argmax(1) == y
    bins = np.minimum((conf * n_bins).astype(int), n_bins - 1)
    d = pd.DataFrame({"bin": bins, "conf": conf, "correct": correct})
    return d.groupby("bin").agg(confidence=("conf", "mean"), accuracy=("correct", "mean"), n=("conf", "size"))


# ---------------------------------------------------------------- "uncertain" rule

def uncertain_mask(probs: np.ndarray, tau: float, margin: float) -> np.ndarray:
    """The rule the app uses: uncertain when top-1 < tau or (top-1 − top-2) < margin."""
    top2 = np.sort(probs, 1)[:, -2:]
    return (top2[:, 1] < tau) | (top2[:, 1] - top2[:, 0] < margin)


def selective(probs: np.ndarray, y: np.ndarray, tau: float, margin: float) -> dict:
    unc = uncertain_mask(probs, tau, margin)
    conf = ~unc
    correct = probs.argmax(1) == y
    return {"coverage": float(conf.mean()), "confident_acc": float(correct[conf].mean()) if conf.any() else float("nan"),
            "uncertain_acc": float(correct[unc].mean()) if unc.any() else float("nan")}


def fit_thresholds(probs: np.ndarray, y: np.ndarray, target_acc: float,
                   taus=np.round(np.arange(0.0, 0.96, 0.01), 2), margins=np.round(np.arange(0.0, 0.51, 0.02), 2)) -> dict:
    """Largest coverage whose confident predictions reach `target_acc` (on validation).
    If no setting reaches it, the most accurate one is returned with `target_met = False`."""
    rows = [{"tau": float(t), "margin": float(m), **selective(probs, y, t, m)} for t in taus for m in margins]
    g = pd.DataFrame(rows).dropna(subset=["confident_acc"])
    ok = g[g["confident_acc"] >= target_acc]
    if len(ok):
        best = ok.sort_values(["coverage", "tau", "margin"], ascending=[False, True, True]).iloc[0]
    else:
        best = g.sort_values(["confident_acc", "coverage"], ascending=False).iloc[0]
    return {**best.to_dict(), "target_acc": target_acc, "target_met": bool(len(ok))}


# ---------------------------------------------------------------- scoring

def score(y: np.ndarray, probs: np.ndarray, labels: list[str]) -> dict:
    pred = probs.argmax(1)
    recall = per_class_recall(y, pred, labels)
    return {"n": int(len(y)), "top1": topk_accuracy(y, probs, 1), "top3": topk_accuracy(y, probs, 3),
            "per_class_recall": recall, "min_recall": float(recall.min()),
            "min_recall_class": str(recall.idxmin()), "pred": pred}


def gate(test: dict, field: dict | None) -> pd.DataFrame:
    """Phase 2 gate. A missing field set counts as not passed: real-world accuracy is the point."""
    rows = [
        ("test top-1", test["top1"], GATE["top1"]),
        ("test top-3", test["top3"], GATE["top3"]),
        ("field top-3", field["top3"] if field else np.nan, GATE["field_top3"]),
        (f"lowest test class recall ({test['min_recall_class']})", test["min_recall"], GATE["min_recall"]),
    ]
    g = pd.DataFrame(rows, columns=["check", "value", "target"])
    g["result"] = np.where(g["value"].isna(), "missing", np.where(g["value"] >= g["target"], "pass", "FAIL"))
    return g


def confusion(y: np.ndarray, pred: np.ndarray, n: int) -> np.ndarray:
    """Row-normalized confusion matrix (row = true class)."""
    m = np.zeros((n, n))
    np.add.at(m, (y, pred), 1)
    return m / np.maximum(m.sum(1, keepdims=True), 1)


def weak_class_advice(recall: pd.Series, cm: np.ndarray, labels: list[str], threshold: float) -> list[str]:
    """For each class under the recall threshold, where its images go: merge or data candidates."""
    out = []
    for c in recall[recall < threshold].sort_values().index:
        i = labels.index(c)
        row = cm[i].copy()
        row[i] = 0
        j = int(row.argmax())
        out.append(f"`{c}`: recall {pct(recall[c])}; {pct(row[j])} of its images are called `{labels[j]}`. "
                   f"Options: merge into `{labels[j]}`, add data, or drop.")
    return out


def golden_set(df: pd.DataFrame, probs: np.ndarray, labels: list[str], n: int = 50, seed: int = 42) -> pd.DataFrame:
    """n test images spread over classes (round-robin, seeded) with the reference top-3, for
    export parity (Phase 3) and browser parity (Phase 6)."""
    rng = np.random.default_rng(seed)
    order = {c: list(rng.permutation(np.flatnonzero(df["label"].to_numpy() == c))) for c in labels}
    picked: list[int] = []
    while len(picked) < min(n, len(df)):
        for c in labels:
            if order[c] and len(picked) < n:
                picked.append(order[c].pop())
    top = np.argsort(-probs[picked], 1)[:, :3]
    g = df.iloc[picked][["rel_path", "label"]].reset_index(drop=True)
    for k in range(3):
        g[f"top{k + 1}"] = [labels[t] for t in top[:, k]]
        g[f"p{k + 1}"] = np.round(probs[picked][np.arange(len(picked)), top[:, k]], 4)
    return g


def field_leaks(field_phash, dataset_phash, max_dist: int = 6) -> np.ndarray:
    """True for field images that are near-copies (pHash) of a dataset image: they'd inflate field accuracy."""
    f, d = phash_to_uint64(pd.Series(field_phash)), phash_to_uint64(pd.Series(dataset_phash))
    hit = np.zeros(len(f), dtype=bool)
    if len(f) and len(d):
        hit[hamming_pairs(f, max_dist, b=d)["i"].to_numpy().astype(int)] = True
    return hit


# ---------------------------------------------------------------- figures

def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(colors="#55554f", labelsize=8)


def plot_confusion(cm: np.ndarray, labels: list[str], path: Path) -> None:
    from matplotlib.colors import LinearSegmentedColormap

    n = len(labels)
    fig, ax = plt.subplots(figsize=(0.32 * n + 2.5, 0.32 * n + 1.8))
    im = ax.imshow(cm, cmap=LinearSegmentedColormap.from_list("blues", SEQ_BLUES), vmin=0, vmax=1)
    ax.set_xticks(range(n), labels, rotation=90, fontsize=7)
    ax.set_yticks(range(n), labels, fontsize=7)
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    for i in range(n):
        for j in range(n):
            if cm[i, j] >= 0.15:  # label only the cells worth reading
                ax.text(j, i, f"{cm[i, j]:.0%}", ha="center", va="center", fontsize=5.5,
                        color="white" if cm[i, j] > 0.5 else "#1f1f1c")
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, label="share of true class")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_reliability(before: pd.DataFrame, after: pd.DataFrame, path: Path, t: float) -> None:
    fig, ax = plt.subplots(figsize=(4.6, 4.2))
    ax.plot([0, 1], [0, 1], color=REF_GRAY, lw=1, ls=":", label="perfect calibration")
    ax.plot(before["confidence"], before["accuracy"], color=BLUE, lw=2, marker="o", ms=5, label="before (T = 1)")
    ax.plot(after["confidence"], after["accuracy"], color=ORANGE, lw=2, marker="o", ms=5, label=f"after (T = {t:.2f})")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("top-1 confidence (validation)")
    ax.set_ylabel("accuracy")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_coverage(probs: np.ndarray, y: np.ndarray, chosen: dict, path: Path) -> None:
    """Accuracy of confident answers vs share answered confidently, sweeping tau (margin fixed at the chosen value)."""
    pts = pd.DataFrame([selective(probs, y, t, chosen["margin"]) for t in np.linspace(0, 0.99, 100)]).dropna()
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    ax.plot(pts["coverage"], pts["confident_acc"], color=BLUE, lw=2)
    ax.axhline(chosen["target_acc"], color=REF_GRAY, lw=1, ls=":")
    ax.text(0.01, chosen["target_acc"] + 0.01, f"target {chosen['target_acc']:.0%}", fontsize=8, color="#55554f")
    ax.plot([chosen["coverage"]], [chosen["confident_acc"]], "o", ms=9, color=BLUE, mec="white", mew=2)
    ax.annotate(f"τ {chosen['tau']:.2f}, margin {chosen['margin']:.2f}", (chosen["coverage"], chosen["confident_acc"]),
                xytext=(10, 8), textcoords="offset points", fontsize=8, color="#1f1f1c")
    ax.set_xlim(0, 1)
    ax.set_xlabel("share of photos answered confidently (validation)")
    ax.set_ylabel("accuracy of confident answers")
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- report

def write_report(out: Path, run_name: str, info: dict, gate_df: pd.DataFrame, calib: dict, test: dict,
                 field: dict | None, table: pd.DataFrame, confused: pd.DataFrame, advice: list[str],
                 figures: dict[str, Path]) -> Path:
    passed = (gate_df["result"] == "pass").all()
    g = gate_df.assign(value=gate_df["value"].map(pct), target=gate_df["target"].map(lambda v: f"≥ {pct(v)}"))
    lines = [
        f"# RockID evaluation · run `{run_name}`", "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "",
        f"## Gate: **{'PASSED' if passed else 'NOT PASSED'}**", "",
        md_table(g, index=False), "",
        "Gate items 4–5 (TF.js within 1 point of the SavedModel, web model ≤ 5 MB) are checked at export (Phase 3).", "",
        "## Summary", "", *[f"- **{k}:** {v}" for k, v in info.items()], "",
        "## Test set", "",
        f"Top-1 **{pct(test['top1'])}**, top-3 **{pct(test['top3'])}** on {test['n']:,} images, preprocessed like the app "
        "(center square crop, bilinear resize to the model size).", "",
    ]
    if field:
        lines += ["## Field set", "", f"Top-1 **{pct(field['top1'])}**, top-3 **{pct(field['top3'])}** on {field['n']} real-world photos "
                  f"({field['n_leaks']} near-copies of dataset images and {field['n_unknown']} of unknown classes left out).", ""]
    else:
        lines += ["## Field set", "", "**Missing.** Add real-world photos to `MyDrive/RockID/field_test/<class>/` "
                  "(10–20 per class) and re-run. The gate cannot pass without it.", ""]
    lines += [
        "## Calibration and the \"uncertain\" result (fitted on validation)", "",
        f"- Temperature **{calib['temperature']:.3f}** · validation ECE {calib['val_ece_before']:.3f} → {calib['val_ece_after']:.3f} "
        f"· NLL {calib['val_nll_before']:.3f} → {calib['val_nll_after']:.3f}",
        f"- Uncertain when top-1 < **{calib['tau']:.2f}** or top-1 − top-2 < **{calib['margin']:.2f}**",
        f"- Target accuracy of confident answers {pct(calib['target_acc'])}: "
        f"{'met' if calib['target_met'] else '**not reachable**, most accurate setting used'}",
        f"- Validation: {pct(calib['val_coverage'])} answered confidently at {pct(calib['val_confident_acc'])} accuracy",
        f"- Test: {pct(calib['test_coverage'])} answered confidently at {pct(calib['test_confident_acc'])} accuracy "
        f"(uncertain answers: {pct(calib['test_uncertain_acc'])})", "",
    ]
    lines += [f"![{k}]({p.parent.name}/{p.name})" for k, p in figures.items()]
    lines += ["", "## Weak classes", ""] + ([f"- {a}" for a in advice] or ["No class below the recall threshold."])
    lines += ["", "## Per-class test results", "", md_table(table), "",
              "## Most confused pairs (test)", "", md_table(confused, index=False) if len(confused) else "none", ""]
    path = out / "eval.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def calibration_json(calib: dict, labels: list[str]) -> str:
    """What export (Phase 3) writes into metadata.json."""
    keep = ("temperature", "tau", "margin", "target_acc")
    return json.dumps({**{k: calib[k] for k in keep}, "labels": labels}, indent=2)
