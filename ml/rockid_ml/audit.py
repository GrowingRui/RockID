"""Orchestration for the Phase 1 dataset audit. The notebook calls these step by step."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
import pandas as pd

from .config import AuditConfig
from .dedup import cosine_pairs, find_clusters, hamming_pairs, phash_to_uint64
from .images import analyze_image
from .scan import scan_dataset
from .split import make_splits

STAT_DTYPES = {"phash": str, "pixel_sha256": str, "decode_error": object}


def _pct(x: float) -> str:
    return "n/a" if pd.isna(x) else f"{x:.1%}"


# ---------------------------------------------------------------- analysis (resumable)

def analyze_all(
    root: str | Path,
    df: pd.DataFrame,
    cache_csv: str | Path | None = None,
    plain_tol: float = 24.0,
    workers: int = 8,
    save_every: int = 2000,
) -> pd.DataFrame:
    """Adds per-image stats to `df`. With `cache_csv` (put it on Drive) progress is saved
    periodically, so a disconnected Colab session resumes instead of starting over."""
    from tqdm.auto import tqdm

    root = Path(root)
    key = ["rel_path", "file_bytes"]
    done = pd.DataFrame(columns=key)
    if cache_csv and Path(cache_csv).exists():
        done = pd.read_csv(cache_csv, dtype=STAT_DTYPES).merge(df[key], on=key)  # drop stale rows

    todo = df[~df["rel_path"].isin(set(done["rel_path"]))][key].to_dict("records")
    fresh: list[dict] = []

    def work(row):
        return {**row, **analyze_image(root / row["rel_path"], plain_tol=plain_tol)}

    def flush():
        if cache_csv:
            pd.concat([done, pd.DataFrame(fresh)], ignore_index=True).to_csv(cache_csv, index=False)

    with ThreadPoolExecutor(workers) as pool:
        for k, rec in enumerate(tqdm(pool.map(work, todo), total=len(todo), desc="analyze"), 1):
            fresh.append(rec)
            if k % save_every == 0:
                flush()
    flush()

    stats = pd.concat([done, pd.DataFrame(fresh)], ignore_index=True)
    out = df.merge(stats, on=key, how="left")
    out["decode_error"] = out["decode_error"].where(out["decode_error"].notna(), None)
    for col in ("grayscale",):
        if col in out:
            out[col] = out[col].map(lambda v: str(v).lower() == "true")
    return out


def cached_embeddings(npz_path: str | Path, rel_paths: Sequence[str], compute: Callable[[], np.ndarray]) -> np.ndarray:
    npz_path = Path(npz_path)
    if npz_path.exists():
        z = np.load(npz_path, allow_pickle=False)
        if z["rel_paths"].tolist() == list(rel_paths):
            return z["emb"]
    emb = compute()
    np.savez(npz_path, emb=emb, rel_paths=np.array(list(rel_paths)))
    return emb


# ---------------------------------------------------------------- duplicates

def near_duplicate_pairs(valid: pd.DataFrame, emb: np.ndarray | None, cfg: AuditConfig) -> pd.DataFrame:
    parts = [hamming_pairs(phash_to_uint64(valid["phash"]), cfg.phash_max_dist)]
    if emb is not None:
        parts.append(cosine_pairs(emb, cfg.emb_min_sim))
    return pd.concat(parts, ignore_index=True)


def assign_clusters(df: pd.DataFrame, valid_mask: pd.Series, pairs: pd.DataFrame) -> pd.Series:
    """Cluster id per row of `df`; rows that failed to decode get -1. `pairs` index the valid rows."""
    valid = df[valid_mask]
    ids = find_clusters(len(valid), pairs, exact_keys=valid["pixel_sha256"])
    out = pd.Series(-1, index=df.index, name="cluster_id")
    out[valid.index] = ids
    return out


# ---------------------------------------------------------------- selection + split

def select_and_split(df: pd.DataFrame, cfg: AuditConfig) -> pd.DataFrame:
    """Applies merges/drops, marks every excluded image with a reason, and splits the rest.
    Adds columns: label_final, cross_class, excluded_reason, split."""
    d = df.copy()
    d["label_final"] = d["label"].map(lambda l: cfg.class_merges.get(l, l))
    reason = pd.Series(None, index=d.index, dtype=object)

    def mark(mask, why):
        reason[np.asarray(mask, dtype=bool) & reason.isna().to_numpy()] = why

    short_side = np.minimum(d["width"].fillna(0), d["height"].fillna(0))
    mark(d["decode_error"].notna(), "decode_error")
    mark(d["label_final"].eq("unlabeled"), "unlabeled")
    mark(d["label_final"].isin(cfg.drop_classes), "dropped_class")
    mark(short_side < cfg.min_side, "too_small")

    alive = reason.isna()
    n_labels = d[alive].groupby("cluster_id")["label_final"].nunique()
    d["cross_class"] = alive & d["cluster_id"].isin(n_labels[n_labels > 1].index)
    if cfg.exclude_cross_class:
        mark(d["cross_class"], "cross_class_duplicate")

    alive = reason.isna()
    dup = d[alive].duplicated("pixel_sha256", keep="first")
    mark(d.index.isin(dup[dup].index), "exact_duplicate")
    d["excluded_reason"] = reason

    kept = d[reason.isna()]
    d["split"] = None
    d.loc[kept.index, "split"] = make_splits(
        kept, label_col="label_final", val_frac=cfg.val_frac, test_frac=cfg.test_frac, seed=cfg.seed
    )
    return d


def manifest(d: pd.DataFrame) -> pd.DataFrame:
    """What gets committed to ml/splits/: enough to rebuild the exact splits from the raw dataset."""
    cols = ["rel_path", "label_final", "family", "pixel_sha256", "cluster_id", "split"]
    m = d[d["split"].notna()][[c for c in cols if c in d]]
    return m.rename(columns={"label_final": "label"}).sort_values("rel_path").reset_index(drop=True)


# ---------------------------------------------------------------- per-class table

def class_table(d: pd.DataFrame, cfg: AuditConfig, probe: dict | None = None, nearest: pd.DataFrame | None = None) -> pd.DataFrame:
    g = d.groupby("label_final")
    reasons = pd.crosstab(d["label_final"], d["excluded_reason"].fillna("clean"))
    clean = d[d["excluded_reason"].isna()].assign(short_side=lambda x: np.minimum(x["width"], x["height"]))
    cg = clean.groupby("label_final")

    t = pd.DataFrame(index=sorted(d["label_final"].unique()))
    t["raw_names"] = g["label_raw"].agg(lambda s: ", ".join(sorted(set(s.dropna()))))
    if "family" in d and d["family"].notna().any():
        t["family"] = g["family"].agg(lambda s: ", ".join(sorted(set(s.dropna()))))
    t["total"] = g.size()
    for col in ("decode_error", "too_small", "exact_duplicate", "cross_class_duplicate", "dropped_class", "clean"):
        t[col] = reasons[col] if col in reasons else 0
    splits = pd.crosstab(clean["label_final"], clean["split"])
    for s in ("train", "val", "test"):
        t[s] = splits[s] if s in splits else 0
    t["dup_rate"] = (t["exact_duplicate"] + t["cross_class_duplicate"]) / t["total"]
    t["plain_bg_share"] = cg["border_plain_frac"].apply(lambda s: (s >= cfg.plain_frac_threshold).mean())
    t["blurry_share"] = cg["blur_var"].apply(lambda s: (s < cfg.blur_low).mean())
    t["grayscale_share"] = cg["grayscale"].mean()
    t["median_short_side"] = cg["short_side"].median()
    if probe is not None:
        t["probe_recall"] = probe["per_class_recall"]
    if nearest is not None:
        t = t.join(nearest)

    def status(r):
        if r.name in cfg.drop_classes or r.name == "unlabeled":
            return "dropped"
        if r["clean"] < cfg.min_images_per_class:
            return "ok (exception)" if r.name in cfg.keep_below_min else "below_min"
        return "ok"

    t["status"] = t.apply(status, axis=1)
    counts = ["total", "decode_error", "too_small", "exact_duplicate", "cross_class_duplicate", "dropped_class", "clean", "train", "val", "test"]
    t[counts] = t[counts].fillna(0).astype(int)
    return t.sort_values("clean", ascending=False)


def recommendations(t: pd.DataFrame, cfg: AuditConfig, probe: dict | None, bg_probe: dict | None, n_cross_clusters: int) -> list[str]:
    recs: list[str] = []
    live = t[t["status"] != "dropped"]
    if len(live) >= 2 and live["clean"].min() > 0:
        ratio = live["clean"].max() / live["clean"].min()
        if ratio > 5:
            recs.append(f"Imbalance ratio is {ratio:.1f}x (largest/smallest class). Use class weights, and consider capping the largest classes.")
    if n_cross_clusters:
        recs.append(f"{n_cross_clusters} duplicate clusters carry more than one label (label noise). Review `review/cross_class.jpg`; they are excluded from the splits.")
    if probe is not None:
        recs.append(
            f"Linear probe on frozen features: top-1 {probe['top1']:.1%}, top-3 {_pct(probe['top3'])} "
            f"(chance {probe['chance']:.1%}). This is a rough floor for fine-tuning, not a prediction of the final score."
        )
    if bg_probe is not None and probe is not None:
        lift = (bg_probe["top1"] - bg_probe["chance"]) / max(probe["top1"] - probe["chance"], 1e-9)
        level = "HIGH" if lift > 0.6 else "moderate" if lift > 0.35 else "low"
        recs.append(
            f"Background-only probe: top-1 {bg_probe['top1']:.1%} with the specimen hidden. That is {lift:.0%} of the full probe's "
            f"gain over chance, so the risk that backgrounds act as a shortcut is {level}. The field test set is what settles it."
        )
        if live["plain_bg_share"].median() < 0.10:
            recs.append(
                "Caveat: most images here are close-ups where the rock fills the frame (few plain backgrounds), so the "
                "\"background-only\" view mostly shows rock texture too. The background probe overstates the shortcut risk "
                "for this dataset; trust the field test set instead."
            )

    for name, r in live.iterrows():
        notes = []
        near = f"`{r['nearest_class']}` (similarity {r['nearest_sim']:.2f})" if "nearest_class" in r and pd.notna(r.get("nearest_class")) else None
        if r["clean"] < cfg.min_images_per_class and name not in cfg.keep_below_min:
            notes.append(f"only {int(r['clean'])} clean images (minimum {cfg.min_images_per_class}): add data, drop, or merge" + (f" into {near}" if near else ""))
        if "probe_recall" in r and pd.notna(r["probe_recall"]) and r["probe_recall"] < 0.5:
            notes.append(f"probe recall {r['probe_recall']:.0%}: at risk of failing the 50% recall gate" + (f"; most similar class is {near}" if near else ""))
        if r["plain_bg_share"] > cfg.studio_class_warn:
            notes.append(f"{r['plain_bg_share']:.0%} plain/studio backgrounds: add field photos")
        if r["dup_rate"] > 0.10:
            notes.append(f"{r['dup_rate']:.0%} duplicates removed")
        if r["blurry_share"] > 0.25:
            notes.append(f"{r['blurry_share']:.0%} blurry images")
        if r["test"] < 20 and r["clean"] >= cfg.min_images_per_class:
            notes.append(f"only {int(r['test'])} test images: per-class metrics will be noisy")
        if notes:
            recs.append(f"**{name}**: " + "; ".join(notes) + ".")
    return recs


# ---------------------------------------------------------------- field test set

def check_field_set(
    field_root: str | Path,
    dataset_valid: pd.DataFrame,
    dataset_emb: np.ndarray | None,
    cfg: AuditConfig,
    embed_fn: Callable[[list[str]], np.ndarray] | None = None,
) -> pd.DataFrame:
    """Scans the field set, maps labels through the merges and flags images that also
    appear in the training dataset (they would inflate field accuracy)."""
    field_root = Path(field_root)
    f = scan_dataset(field_root)
    if f.empty:
        return f
    f = analyze_all(field_root, f, plain_tol=cfg.plain_tol)
    v = f[f["decode_error"].isna()].reset_index(drop=True)

    leak = set(hamming_pairs(phash_to_uint64(v["phash"]), cfg.phash_max_dist, b=phash_to_uint64(dataset_valid["phash"]))["i"])
    if embed_fn is not None and dataset_emb is not None:
        fe = embed_fn([str(field_root / p) for p in v["rel_path"]])
        leak |= set(cosine_pairs(fe, cfg.emb_min_sim, b=dataset_emb)["i"])

    v["label_final"] = v["label"].map(lambda l: cfg.class_merges.get(l, l))
    v["leaks_into_dataset"] = v.index.isin(sorted(leak))
    v["known_class"] = v["label_final"].isin(set(dataset_valid["label"].map(lambda l: cfg.class_merges.get(l, l))) - set(cfg.drop_classes))
    return v
