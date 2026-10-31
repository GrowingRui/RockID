from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold


def make_splits(
    df: pd.DataFrame,
    label_col: str = "label",
    group_col: str = "cluster_id",
    val_frac: float = 0.15,
    test_frac: float = 0.15,
    seed: int = 42,
    n_folds: int = 20,
) -> pd.Series:
    """Stratified by label, grouped by duplicate cluster: a cluster never spans two splits.
    The data is cut into `n_folds` stratified group folds, which are then assigned to test/val/train."""
    n_test = max(1, round(test_frac * n_folds))
    n_val = max(1, round(val_frac * n_folds))
    if n_test + n_val >= n_folds:
        raise ValueError("val_frac + test_frac leaves no folds for training")

    fold = np.full(len(df), -1)
    cv = StratifiedGroupKFold(n_splits=n_folds, shuffle=True, random_state=seed)
    for k, (_, idx) in enumerate(cv.split(np.zeros(len(df)), df[label_col], df[group_col])):
        fold[idx] = k
    split = np.where(fold < n_test, "test", np.where(fold < n_test + n_val, "val", "train"))
    return pd.Series(split, index=df.index, name="split")


def leaking_clusters(df: pd.DataFrame, group_col: str = "cluster_id", split_col: str = "split") -> pd.Series:
    """Clusters found in more than one split (must be empty)."""
    n = df.groupby(group_col)[split_col].nunique()
    return n[n > 1]


def split_counts(df: pd.DataFrame, label_col: str = "label", split_col: str = "split") -> pd.DataFrame:
    t = pd.crosstab(df[label_col], df[split_col])
    return t.reindex(columns=["train", "val", "test"], fill_value=0)
