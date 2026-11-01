"""Classification metrics and class weights (numpy only, shared by training and evaluation)."""

from __future__ import annotations

import numpy as np
import pandas as pd

# Phase 2 go/no-go gate (docs/PHASES.md), lowered for class list v2 by ADR 0003 (was 0.75 / 0.90 / 0.70 / 0.50).
# Checked on the test and field sets in 03_evaluate.
GATE = {"top1": 0.60, "top3": 0.80, "field_top3": 0.65, "min_recall": 0.40}


def topk_accuracy(y_true: np.ndarray, scores: np.ndarray, k: int) -> float:
    """Share of rows whose true class index is among the k highest scores."""
    y_true = np.asarray(y_true)
    topk = np.argpartition(-scores, kth=min(k, scores.shape[1]) - 1, axis=1)[:, :k]
    return float((topk == y_true[:, None]).any(1).mean())


def per_class_recall(y_true: np.ndarray, y_pred: np.ndarray, labels: list[str]) -> pd.Series:
    """Recall per class (index = label name); NaN for classes without examples."""
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    n = len(labels)
    hits = np.bincount(y_true[y_true == y_pred], minlength=n)
    support = np.bincount(y_true, minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return pd.Series(hits / np.where(support, support, np.nan), index=labels, name="recall")


def class_weights(y: np.ndarray, n_classes: int, power: float = 1.0) -> np.ndarray:
    """Inverse-frequency weights `(N / (K * count)) ** power`, rescaled so the average weight over the
    training samples is 1 (the loss scale, and so the learning rate, stays comparable). power 0 = off, 0.5 = softened."""
    counts = np.bincount(np.asarray(y), minlength=n_classes).astype(float)
    if (counts == 0).any():
        raise ValueError("every class needs at least one training image")
    w = (counts.sum() / (n_classes * counts)) ** power
    return w / (w[y].mean())


def summarize(y_true: np.ndarray, logits: np.ndarray, labels: list[str]) -> dict:
    pred = logits.argmax(1)
    recall = per_class_recall(y_true, pred, labels)
    return {
        "n": int(len(y_true)),
        "top1": topk_accuracy(y_true, logits, 1),
        "top3": topk_accuracy(y_true, logits, 3),
        "min_recall": float(recall.min()),
        "min_recall_class": str(recall.idxmin()),
        "per_class_recall": recall,
        "pred": pred,
    }
