from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

_POPCOUNT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)
MAX_PAIRS = 5_000_000


def phash_to_uint64(hexes) -> np.ndarray:
    return np.array([int(h, 16) for h in hexes], dtype=np.uint64)


def _hamming(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    x = np.ascontiguousarray(np.bitwise_xor(a[:, None], b[None, :]))
    return _POPCOUNT[x.view(np.uint8)].reshape(x.shape + (8,)).sum(-1, dtype=np.int32)


def _pairs(score_fn, a, b, keep, chunk: int, kind: str) -> pd.DataFrame:
    """Shared chunked pair search. When `b` is None, compares `a` with itself (i < j only)."""
    self_mode = b is None
    other = a if self_mode else b
    parts, total = [], 0
    for start in range(0, len(a), chunk):
        scores = score_fn(a[start : start + chunk], other)
        ii, jj = np.nonzero(keep(scores))
        vals = scores[ii, jj]
        ii = ii + start
        if self_mode:
            m = jj > ii
            ii, jj, vals = ii[m], jj[m], vals[m]
        parts.append(pd.DataFrame({"i": ii, "j": jj, "score": vals.astype(float)}))
        total += len(ii)
        if total > MAX_PAIRS:
            raise RuntimeError(
                f"{kind}: more than {MAX_PAIRS:,} candidate pairs; the threshold is too loose."
            )
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["i", "j", "score"])
    out["kind"] = kind
    return out


def hamming_pairs(a: np.ndarray, max_dist: int, b: np.ndarray | None = None, chunk: int = 256) -> pd.DataFrame:
    return _pairs(_hamming, a, b, lambda d: d <= max_dist, chunk, "phash")


def cosine_pairs(a: np.ndarray, min_sim: float, b: np.ndarray | None = None, chunk: int = 1024) -> pd.DataFrame:
    """Embeddings must be L2-normalized."""
    return _pairs(lambda x, y: x @ y.T, a, b, lambda s: s >= min_sim, chunk, "embedding")


class UnionFind:
    def __init__(self, n: int):
        self.parent = np.arange(n)

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def find_clusters(n: int, pairs: pd.DataFrame, exact_keys: pd.Series | None = None) -> np.ndarray:
    """Connected components over near-duplicate pairs plus exact-hash groups.
    Returns a dense cluster id per row (singletons get their own id)."""
    uf = UnionFind(n)
    for i, j in zip(pairs["i"].to_numpy(), pairs["j"].to_numpy()):
        uf.union(int(i), int(j))
    if exact_keys is not None:
        for idx in exact_keys.reset_index(drop=True).groupby(exact_keys.to_numpy()).indices.values():
            for k in idx[1:]:
                uf.union(int(idx[0]), int(k))
    roots = np.array([uf.find(i) for i in range(n)])
    _, dense = np.unique(roots, return_inverse=True)
    return dense


def cluster_summary(df: pd.DataFrame, label_col: str = "label", cluster_col: str = "cluster_id") -> pd.DataFrame:
    g = df.groupby(cluster_col)[label_col]
    out = pd.DataFrame({"size": g.size(), "n_labels": g.nunique(), "labels": g.agg(lambda s: sorted(set(s)))})
    big = out[out["size"] > 25]
    if len(big):
        warnings.warn(
            f"{len(big)} duplicate clusters have more than 25 images (largest {int(big['size'].max())}). "
            "Check the cluster contact sheet: thresholds may be chaining distinct images together.",
            stacklevel=2,
        )
    return out
