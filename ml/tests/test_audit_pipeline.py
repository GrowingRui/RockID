"""End-to-end audit on a small synthetic dataset (no TensorFlow needed)."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from rockid_ml import audit, probes, report
from rockid_ml.config import AuditConfig
from rockid_ml.dedup import cosine_pairs, find_clusters, hamming_pairs, phash_to_uint64
from rockid_ml.scan import scan_dataset, slugify
from rockid_ml.split import leaking_clusters

N_PER_CLASS = 40


def _pattern(rng: np.random.Generator, size: int = 128) -> Image.Image:
    low = rng.integers(0, 256, (8, 8, 3), dtype=np.uint8)
    im = Image.fromarray(low).resize((size, size), Image.BICUBIC)
    a = np.asarray(im).astype(np.int16) + rng.integers(-6, 7, (size, size, 3))
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


@pytest.fixture(scope="module")
def dataset(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("ds")
    rng = np.random.default_rng(0)
    # Same class under two folder spellings and split folders: must merge into one slug.
    dirs = {"granite": ["Train/Granite", "test/granite"], "quartz": ["Train/Quartz"], "pyrite": ["Train/Pyrite"]}
    for cls, folders in dirs.items():
        for k in range(N_PER_CLASS):
            d = root / folders[k % len(folders)]
            d.mkdir(parents=True, exist_ok=True)
            _pattern(rng).save(d / f"{cls}_{k}.jpg", quality=95)

    g = root / "Train/Granite"
    shutil.copy(g / "granite_0.jpg", g / "granite_0_copy.jpg")  # exact duplicate
    Image.open(g / "granite_2.jpg").resize((96, 96)).save(g / "granite_2_small.jpg", quality=90)  # near-duplicate
    shutil.copy(root / "Train/Quartz/quartz_0.jpg", root / "Train/Pyrite/pyrite_mislabeled.jpg")  # cross-class
    (g / "broken.jpg").write_bytes(b"not an image")
    _pattern(rng, 32).save(g / "tiny.jpg")
    (root / "labels.csv").write_text("file,label\n")
    return root


@pytest.fixture(scope="module")
def audited(dataset):
    cfg = AuditConfig(min_images_per_class=30, emb_min_sim=0.99)
    df = audit.analyze_all(dataset, scan_dataset(dataset), workers=4)
    valid_mask = df["decode_error"].isna()
    pairs = audit.near_duplicate_pairs(df[valid_mask].reset_index(drop=True), None, cfg)
    df["cluster_id"] = audit.assign_clusters(df, valid_mask, pairs)
    return cfg, audit.select_and_split(df, cfg)


def row(d: pd.DataFrame, name: str) -> pd.Series:
    return d[d["rel_path"].str.endswith(name)].iloc[0]


def test_slugify():
    assert slugify("Rose Quartz") == "rose-quartz"
    assert slugify("Ágata (Agate)") == "agata-agate"


def test_scan_merges_folder_spellings_and_ignores_split_dirs(dataset):
    df = scan_dataset(dataset)
    assert set(df["label"]) == {"granite", "quartz", "pyrite"}
    assert set(df["source_split"].dropna()) == {"train", "test"}


def test_exclusions(audited):
    _, d = audited
    assert row(d, "broken.jpg")["excluded_reason"] == "decode_error"
    assert row(d, "tiny.jpg")["excluded_reason"] == "too_small"
    assert row(d, "granite_0_copy.jpg")["excluded_reason"] == "exact_duplicate"
    assert pd.isna(row(d, "granite_0.jpg")["excluded_reason"])
    assert row(d, "pyrite_mislabeled.jpg")["excluded_reason"] == "cross_class_duplicate"
    assert row(d, "quartz_0.jpg")["excluded_reason"] == "cross_class_duplicate"


def test_near_duplicate_shares_cluster_and_split(audited):
    _, d = audited
    a, b = row(d, "granite_2.jpg"), row(d, "granite_2_small.jpg")
    assert a["cluster_id"] == b["cluster_id"]
    assert a["split"] == b["split"]


def test_no_leakage_and_all_splits_present(audited):
    _, d = audited
    kept = d[d["split"].notna()]
    assert leaking_clusters(kept).empty
    counts = pd.crosstab(kept["label_final"], kept["split"])
    assert (counts[["train", "val", "test"]] > 0).all().all()
    share = kept["split"].value_counts(normalize=True)
    assert 0.6 < share["train"] < 0.8


def test_merges_and_drops(dataset, audited):
    cfg, d0 = audited
    cfg2 = AuditConfig(min_images_per_class=30, class_merges={"pyrite": "quartz"}, drop_classes=["granite"])
    d = audit.select_and_split(d0.drop(columns=["label_final", "cross_class", "excluded_reason", "split"]), cfg2)
    assert set(d[d["split"].notna()]["label_final"]) == {"quartz"}
    # After merging, the quartz/pyrite copy is no longer cross-class: exactly one copy stays clean.
    reasons = {row(d, n)["excluded_reason"] for n in ("quartz_0.jpg", "pyrite_mislabeled.jpg")}
    assert len(reasons) == 2 and "exact_duplicate" in reasons and any(pd.isna(r) for r in reasons)


def test_split_is_deterministic(audited):
    cfg, d = audited
    again = audit.select_and_split(d.drop(columns=["label_final", "cross_class", "excluded_reason", "split"]), cfg)
    pd.testing.assert_series_equal(d["split"], again["split"])


def test_hamming_and_cosine_cross_pairs():
    a = phash_to_uint64(["ffffffffffffffff", "0000000000000000"])
    b = phash_to_uint64(["fffffffffffffff0"])
    p = hamming_pairs(a, 6, b=b)
    assert p[["i", "j"]].values.tolist() == [[0, 0]] and p["score"].iloc[0] == 4
    e = np.eye(3, dtype=np.float32)
    assert len(cosine_pairs(e, 0.9)) == 0
    assert len(cosine_pairs(np.vstack([e, e[:1]]), 0.9)) == 1


def test_find_clusters_transitive():
    pairs = pd.DataFrame({"i": [0, 1], "j": [1, 2]})
    ids = find_clusters(5, pairs, exact_keys=pd.Series(["x", "y", "z", "q", "q"]))
    assert ids[0] == ids[1] == ids[2] and ids[3] == ids[4] and ids[0] != ids[3]


def test_probes_on_separable_embeddings():
    rng = np.random.default_rng(1)
    centers = rng.normal(size=(3, 32))
    labels = np.repeat(np.array(["a", "b", "c"]), 60)
    emb = centers[np.searchsorted(["a", "b", "c"], labels)] + 0.1 * rng.normal(size=(180, 32))
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    res = probes.linear_probe(emb, labels, groups=np.arange(180))
    assert res["top1"] > 0.95
    near = probes.nearest_classes(emb, labels)
    assert set(near.index) == {"a", "b", "c"}


def test_report_end_to_end(dataset, audited, tmp_path):
    cfg, d = audited
    t = audit.class_table(d, cfg)
    recs = audit.recommendations(t, cfg, None, None, n_cross_clusters=int(d["cross_class"].any()))
    figs = {
        "class_counts": tmp_path / "figures/class_counts.png",
        "plain_bg": tmp_path / "figures/plain_bg.png",
        "blur": tmp_path / "figures/blur.png",
        "short_side": tmp_path / "figures/short_side.png",
    }
    figs["class_counts"].parent.mkdir()
    report.plot_class_counts(t, figs["class_counts"], cfg.min_images_per_class)
    report.plot_share(t, "plain_bg_share", figs["plain_bg"], "share", cfg.studio_class_warn)
    report.plot_hist(d["blur_var"], figs["blur"], "blur", cfg.blur_low, log=True)
    report.plot_hist(np.minimum(d["width"], d["height"]), figs["short_side"], "px")
    sheet = report.contact_sheet(
        report.cluster_rows(d, dataset, [row(d, "granite_2.jpg")["cluster_id"]]), tmp_path / "review/clusters.jpg"
    )
    path = report.write_report(
        tmp_path, cfg.to_dict(), {"images": len(d)}, t, None, ["labels.csv"], {"granite": ["Granite", "granite"]},
        {"exact": 1}, None, None, None, None, recs, [sheet], figs,
    )
    text = path.read_text(encoding="utf-8")
    assert "## Classes" in text and "granite" in text and "cross_class_duplicate" in text
    m = audit.manifest(d)
    assert set(m.columns) == {"rel_path", "label", "family", "pixel_sha256", "cluster_id", "split"}


def test_label_from_filename():
    from rockid_ml.scan import label_from_filename

    assert label_from_filename("100Andesite.png") == "andesite"
    assert label_from_filename("Andesite12.png") == "andesite"
    assert label_from_filename("Quartz_diorite3.jpg") == "quartz-diorite"
    assert label_from_filename("12_Oil_shale (2).jpeg") == "oil-shale"


def test_scan_filename_mode_keeps_folder_as_family(dataset):
    df = scan_dataset(dataset, label_from="filename")
    g = df[df["rel_path"].str.endswith("granite_3.jpg")].iloc[0]
    assert g["label"] == "granite" and g["family"] == "granite"
    assert df.loc[df["rel_path"].str.endswith("pyrite_mislabeled.jpg"), "label"].item() == "pyrite-mislabeled"


def test_class_config(tmp_path):
    import json

    from rockid_ml.classes import final_classes, load_class_config, validate_class_config

    p = tmp_path / "c.json"
    p.write_text(json.dumps({"merges": {"pyrite": "quartz", "typo": "quartz"}, "drop": ["granite"]}))
    cc = load_class_config(p)
    labels = {"granite", "quartz", "pyrite"}
    assert validate_class_config(cc, labels) == ["merge source `typo` is not a dataset class"]
    assert final_classes(cc, labels) == ["quartz"]
    cc["merges"]["quartz"] = "granite"
    probs = validate_class_config(cc, labels)
    assert any("both a merge target and dropped" in x for x in probs) and any("chained merge" in x for x in probs)


def test_repo_class_config_v1_is_consistent():
    from rockid_ml.classes import load_class_config, validate_class_config

    cc = load_class_config(Path(__file__).parents[1] / "configs" / "classes_v1.json")
    known = set(cc["merges"]) | set(cc["drop"])
    problems = [p for p in validate_class_config(cc, known) if "is not a dataset class" not in p]
    assert problems == []
    assert not set(cc["keep_below_min"]) & set(cc["drop"])


def test_class_too_small_to_split_is_excluded_not_fatal():
    from rockid_ml.audit import SPLIT_FOLDS, select_and_split

    n_big, n_small = 60, SPLIT_FOLDS - 5
    df = pd.DataFrame({
        "rel_path": [f"x{i}.jpg" for i in range(n_big + n_small)],
        "label": ["big"] * n_big + ["small"] * n_small,
        "decode_error": None, "width": 200, "height": 200,
        "pixel_sha256": [f"h{i}" for i in range(n_big + n_small)],
        "cluster_id": range(n_big + n_small),
    })
    d = select_and_split(df, AuditConfig())
    assert (d.loc[d["label"] == "small", "excluded_reason"] == "too_few_images").all()
    assert d.loc[d["label"] == "big", "split"].notna().all()
