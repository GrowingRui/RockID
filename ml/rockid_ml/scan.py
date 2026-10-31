from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

from .images import is_image_file

# Folder names that describe a pre-made split rather than a class. We re-split ourselves,
# so these are recorded but never used as labels.
SPLIT_DIR_NAMES = {"train", "training", "test", "testing", "val", "valid", "validation"}
LABEL_FILE_EXTS = {".csv", ".json", ".txt", ".tsv", ".xml"}


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "unknown"


def _skip(parts: tuple[str, ...]) -> bool:
    return any(p.startswith(".") or p == "__MACOSX" for p in parts)


def label_from_filename(name: str) -> str:
    """`100Andesite.png`, `Andesite12.png`, `Quartz_diorite3.jpg` -> `andesite`, `andesite`, `quartz-diorite`."""
    return slugify(_name_part(name))


def _name_part(name: str) -> str:
    """File name without extension and without leading/trailing counters."""
    return re.sub(r"^[\d_\- ()]+|[\d_\- ()]+$", "", Path(name).stem)


def scan_dataset(root: str | Path, label_from: str = "folder") -> pd.DataFrame:
    """One row per image. With `label_from="folder"` the label is the parent folder name, slugified,
    so `Train/Granite` and `test/granite` end up in the same class. With `"filename"` the label comes
    from the file name and the folder becomes `family` (e.g. igneous/metamorphic/sedimentary)."""
    if label_from not in ("folder", "filename"):
        raise ValueError(f"label_from must be 'folder' or 'filename', got {label_from!r}")
    root = Path(root)
    rows = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if _skip(rel.parts) or not is_image_file(p):
            continue
        parents = rel.parts[:-1]
        label_raw = parents[-1] if parents else None
        if label_raw is not None and label_raw.lower() in SPLIT_DIR_NAMES:
            label_raw = None  # images sit directly in a split folder: no class folder
        family = slugify(label_raw) if label_raw else None
        if label_from == "filename":
            label_raw = _name_part(p.name)
            label = slugify(label_raw)
        else:
            label = family or "unlabeled"
        rows.append(
            {
                "rel_path": rel.as_posix(),
                "label_raw": label_raw,
                "label": label,
                "family": family,
                "source_split": next((d.lower() for d in parents if d.lower() in SPLIT_DIR_NAMES), None),
                "source_dirs": "/".join(parents[:-1]),
                "file_bytes": p.stat().st_size,
            }
        )
    cols = ["rel_path", "label_raw", "label", "family", "source_split", "source_dirs", "file_bytes"]
    return pd.DataFrame(rows, columns=cols)


def find_label_files(root: str | Path) -> list[str]:
    """CSV/JSON/TXT files in the dataset: a hint that labels may live outside the folder names."""
    root = Path(root)
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in LABEL_FILE_EXTS and not _skip(p.relative_to(root).parts)
    )


def raw_name_map(df: pd.DataFrame) -> dict[str, list[str]]:
    """slug -> raw folder names that were merged into it (spot accidental merges)."""
    return {
        slug: sorted(g.dropna().unique().tolist())
        for slug, g in df.groupby("label")["label_raw"]
    }
