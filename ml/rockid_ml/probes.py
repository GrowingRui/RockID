"""Cheap pre-training diagnostics on frozen embeddings.

A linear probe gives a rough floor for what fine-tuning can reach; fine-tuning usually does better.
The background probe repeats it with the specimen hidden: if backgrounds alone predict the class
well above chance, the model can learn a shortcut that will fail on field photos."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import top_k_accuracy_score
from sklearn.model_selection import StratifiedGroupKFold


def linear_probe(emb: np.ndarray, labels: np.ndarray, groups: np.ndarray, seed: int = 42, n_splits: int = 5) -> dict:
    labels = np.asarray(labels)
    classes = np.unique(labels)
    proba = np.zeros((len(labels), len(classes)))
    cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for tr, te in cv.split(emb, labels, groups):
        clf = LogisticRegression(max_iter=3000, C=10.0, class_weight="balanced")
        clf.fit(emb[tr], labels[tr])
        cols = np.searchsorted(classes, clf.classes_)
        proba[np.ix_(te, cols)] = clf.predict_proba(emb[te])

    pred = classes[proba.argmax(1)]
    recall = pd.Series(pred == labels).groupby(labels).mean()
    return {
        "top1": float((pred == labels).mean()),
        "top3": float(top_k_accuracy_score(labels, proba, k=3, labels=classes)) if len(classes) > 3 else float("nan"),
        "chance": 1.0 / len(classes),
        "majority": float(pd.Series(labels).value_counts(normalize=True).iloc[0]),
        "per_class_recall": recall,
        "pred": pred,
    }


def nearest_classes(emb: np.ndarray, labels: np.ndarray) -> pd.DataFrame:
    """For each class, the class whose mean embedding is most similar: first merge candidate."""
    labels = np.asarray(labels)
    classes = np.unique(labels)
    cent = np.stack([emb[labels == c].mean(0) for c in classes])
    cent /= np.linalg.norm(cent, axis=1, keepdims=True)
    sim = cent @ cent.T
    np.fill_diagonal(sim, -np.inf)
    j = sim.argmax(1)
    return pd.DataFrame({"nearest_class": classes[j], "nearest_sim": sim[np.arange(len(classes)), j]}, index=classes)


def confused_pairs(labels: np.ndarray, pred: np.ndarray, top: int = 15) -> pd.DataFrame:
    """Most frequent (true, predicted) mistakes, as a share of the true class."""
    s = pd.DataFrame({"true": labels, "pred": pred})
    n = s["true"].value_counts()
    wrong = s[s["true"] != s["pred"]].value_counts().rename("count").reset_index()
    wrong["share_of_true"] = wrong["count"] / wrong["true"].map(n)
    return wrong.sort_values("share_of_true", ascending=False).head(top).reset_index(drop=True)
