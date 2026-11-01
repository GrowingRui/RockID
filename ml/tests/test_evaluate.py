"""Calibration, uncertain thresholds, gate and report (numpy only)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rockid_ml import evaluate

LABELS = ["a", "b", "c", "d"]


def _overconfident(n=2000, seed=0):
    """Logits whose softmax is too confident: true accuracy ~70 %, confidence near 100 %."""
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 4, n)
    pred = np.where(rng.random(n) < 0.7, y, rng.integers(0, 4, n))
    logits = rng.normal(0, 0.3, (n, 4))
    logits[np.arange(n), pred] += 8.0
    return logits, y


def test_temperature_fixes_overconfidence_without_changing_predictions():
    logits, y = _overconfident()
    t = evaluate.fit_temperature(logits, y)
    assert t > 1.5
    assert evaluate.nll(logits, y, t) < evaluate.nll(logits, y)
    before, after = evaluate.softmax(logits), evaluate.softmax(logits, t)
    assert evaluate.ece(after, y) < evaluate.ece(before, y) / 2
    assert (before.argmax(1) == after.argmax(1)).all()


def test_uncertain_rule():
    p = np.array([[0.9, 0.05, 0.05, 0.0], [0.45, 0.40, 0.1, 0.05], [0.3, 0.3, 0.2, 0.2]])
    assert evaluate.uncertain_mask(p, tau=0.5, margin=0.1).tolist() == [False, True, True]
    assert evaluate.uncertain_mask(p, tau=0.4, margin=0.0).tolist() == [False, False, True]


def test_fit_thresholds_meets_target_and_flags_impossible():
    # Like a real model: correct answers tend to be more confident, so a threshold can select them.
    rng = np.random.default_rng(1)
    n = 2000
    y = rng.integers(0, 4, n)
    right = rng.random(n) < 0.7
    pred = np.where(right, y, (y + rng.integers(1, 4, n)) % 4)
    logits = rng.normal(0, 0.3, (n, 4))
    logits[np.arange(n), pred] += np.where(right, rng.uniform(1, 6, n), rng.uniform(0, 3, n))
    p = evaluate.softmax(logits, evaluate.fit_temperature(logits, y))
    thr = evaluate.fit_thresholds(p, y, target_acc=0.8)
    assert thr["target_met"] and thr["confident_acc"] >= 0.8 and 0 < thr["coverage"] < 1
    assert evaluate.selective(p, y, thr["tau"], thr["margin"])["coverage"] == pytest.approx(thr["coverage"])
    assert not evaluate.fit_thresholds(p, y, target_acc=1.01)["target_met"]


def test_gate_and_missing_field_set():
    test = {"top1": 0.8, "top3": 0.95, "min_recall": 0.3, "min_recall_class": "c"}
    g = evaluate.gate(test, None)
    assert g["result"].tolist() == ["pass", "pass", "missing", "FAIL"]
    g = evaluate.gate({**test, "min_recall": 0.6}, {"top3": 0.75})
    assert (g["result"] == "pass").all()


def test_confusion_and_weak_class_advice():
    y = np.array([0, 0, 0, 0, 1, 1, 2, 2, 3, 3])
    pred = np.array([1, 1, 1, 0, 1, 1, 2, 2, 3, 3])
    cm = evaluate.confusion(y, pred, 4)
    assert np.allclose(cm.sum(1), 1) and cm[0, 1] == 0.75
    recall = evaluate.score(y, np.eye(4)[pred], LABELS)["per_class_recall"]
    advice = evaluate.weak_class_advice(recall, cm, LABELS, 0.5)
    assert len(advice) == 1 and "`a`" in advice[0] and "`b`" in advice[0]


def test_golden_set_spreads_over_classes():
    df = pd.DataFrame({"rel_path": [f"x{i}.png" for i in range(40)], "label": [LABELS[i % 4] for i in range(40)]})
    probs = evaluate.softmax(np.random.default_rng(0).normal(size=(40, 4)))
    g = evaluate.golden_set(df, probs, LABELS, n=10)
    assert len(g) == 10 and g["rel_path"].is_unique
    assert g["label"].value_counts().min() >= 2
    assert (g["p1"] >= g["p2"]).all() and set(g["top1"]) <= set(LABELS)
    assert g.equals(evaluate.golden_set(df, probs, LABELS, n=10))  # seeded


def test_field_leaks():
    ds = ["ffffffffffffffff", "0000000000000000"]
    field = ["fffffffffffffffe", "0f0f0f0f0f0f0f0f"]  # 1 bit from ds[0]; far from both
    assert evaluate.field_leaks(field, ds).tolist() == [True, False]
    assert evaluate.field_leaks([], ds).tolist() == []


def test_report_and_figures(tmp_path):
    logits, y = _overconfident(400)
    t = evaluate.fit_temperature(logits, y)
    p_raw, p = evaluate.softmax(logits), evaluate.softmax(logits, t)
    thr = evaluate.fit_thresholds(p, y, 0.8)
    test = evaluate.score(y, p, LABELS)
    cm = evaluate.confusion(y, test["pred"], 4)
    fig = tmp_path / "figures"
    fig.mkdir()
    figures = {"cm": fig / "cm.png", "rel": fig / "rel.png", "cov": fig / "cov.png"}
    evaluate.plot_confusion(cm, LABELS, figures["cm"])
    evaluate.plot_reliability(evaluate.reliability(p_raw, y), evaluate.reliability(p, y), figures["rel"], t)
    evaluate.plot_coverage(p, y, {**thr, "target_acc": 0.8}, figures["cov"])
    calib = {"temperature": t, **thr, "val_ece_before": 0.2, "val_ece_after": 0.05, "val_nll_before": 1.0,
             "val_nll_after": 0.8, "val_coverage": thr["coverage"], "val_confident_acc": thr["confident_acc"],
             "test_coverage": 0.5, "test_confident_acc": 0.9, "test_uncertain_acc": 0.5}
    table = pd.DataFrame({"recall": test["per_class_recall"]})
    path = evaluate.write_report(tmp_path, "run", {"Model": "x"}, evaluate.gate(test, None), calib, test, None,
                                 table, pd.DataFrame(), [], figures)
    text = path.read_text(encoding="utf-8")
    assert "NOT PASSED" in text and "Field set" in text and "figures/cm.png" in text
    assert all(f.stat().st_size > 0 for f in figures.values())
    assert '"temperature"' in evaluate.calibration_json(calib, LABELS)
