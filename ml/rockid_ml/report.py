"""Figures, contact sheets and the markdown audit report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from .images import load_rgb  # noqa: E402

TRAINING_ONLY_POLICY = (
    "Images in this dataset appear to be collected from the web, so the dataset license may not cover "
    "the copyright of each image. RockID uses them **for training and evaluation only**. They are never "
    "redistributed, shown in the app, or used as encyclopedia images. Encyclopedia images come from "
    "Wikimedia Commons with per-image licenses (Phase 8)."
)


# ---------------------------------------------------------------- markdown helpers

def md_table(df: pd.DataFrame, floatfmt: str = ".2f", index: bool = True) -> str:
    d = df.reset_index() if index else df
    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return "" if np.isnan(v) else format(v, floatfmt)
        return str(v).replace("|", "\\|")
    head = "| " + " | ".join(map(str, d.columns)) + " |"
    sep = "|" + "|".join("---" for _ in d.columns) + "|"
    rows = ["| " + " | ".join(fmt(v) for v in r) + " |" for r in d.itertuples(index=False)]
    return "\n".join([head, sep, *rows])


def pct(x: float) -> str:
    return "n/a" if pd.isna(x) else f"{x:.1%}"


# ---------------------------------------------------------------- figures

def plot_class_counts(t: pd.DataFrame, path: Path, min_images: int) -> None:
    t = t.sort_values("clean")
    fig, ax = plt.subplots(figsize=(8, max(3, 0.28 * len(t))))
    ax.barh(t.index, t["clean"], color="#7a6a58", label="clean")
    ax.barh(t.index, t["total"] - t["clean"], left=t["clean"], color="#d9cfc3", label="excluded")
    ax.axvline(min_images, color="#b0413e", ls="--", lw=1, label=f"minimum ({min_images})")
    ax.set_xlabel("images")
    ax.legend(loc="lower right", frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_share(t: pd.DataFrame, col: str, path: Path, xlabel: str, warn: float | None = None) -> None:
    t = t.sort_values(col)
    fig, ax = plt.subplots(figsize=(8, max(3, 0.28 * len(t))))
    ax.barh(t.index, t[col], color="#7a6a58")
    if warn is not None:
        ax.axvline(warn, color="#b0413e", ls="--", lw=1)
    ax.set_xlim(0, 1)
    ax.set_xlabel(xlabel)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_hist(values: pd.Series, path: Path, xlabel: str, vline: float | None = None, log: bool = False) -> None:
    v = values.dropna()
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.hist(np.log10(v.clip(lower=1e-3)) if log else v, bins=50, color="#7a6a58")
    if vline is not None:
        ax.axvline(np.log10(vline) if log else vline, color="#b0413e", ls="--", lw=1)
    ax.set_xlabel(f"log10({xlabel})" if log else xlabel)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------- contact sheets

def contact_sheet(items: Iterable[tuple[str | Path, str]], out: Path, cols: int = 8, thumb: int = 160, rows_of: int | None = None) -> Path | None:
    """Grid of thumbnails with captions. `rows_of` starts a new row every N items (for clusters)."""
    items = list(items)
    if not items:
        return None
    cap_h = 16
    if rows_of:
        cols = rows_of
    n_rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb, n_rows * (thumb + cap_h)), (245, 242, 238))
    draw = ImageDraw.Draw(sheet)
    for k, (path, caption) in enumerate(items):
        x, y = (k % cols) * thumb, (k // cols) * (thumb + cap_h)
        if path:
            try:
                im = load_rgb(path)
                im.thumbnail((thumb - 4, thumb - 4))
                sheet.paste(im, (x + (thumb - im.width) // 2, y + (thumb - im.height) // 2))
            except Exception:
                draw.text((x + 6, y + thumb // 2), "unreadable", fill=(176, 65, 62))
        draw.text((x + 3, y + thumb + 2), caption[: thumb // 6], fill=(40, 34, 28))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=85)
    return out


def cluster_rows(d: pd.DataFrame, root: Path, clusters: Iterable[int], per_row: int = 6) -> list[tuple[str, str]]:
    """Flattens clusters into fixed-width rows, padding with blanks."""
    items: list[tuple[str, str]] = []
    for cid in clusters:
        members = d[d["cluster_id"] == cid].head(per_row)
        row = [(str(root / r.rel_path), f"#{cid} {r.label_final}") for r in members.itertuples()]
        items += row + [("", "")] * (per_row - len(row))
    return items


# ---------------------------------------------------------------- report

def write_report(
    out_dir: Path,
    cfg_dict: dict,
    summary: dict,
    t: pd.DataFrame,
    license_info: dict | None,
    label_files: list[str],
    merged_raw_names: dict[str, list[str]],
    dup_stats: dict,
    probe: dict | None,
    bg_probe: dict | None,
    confused: pd.DataFrame | None,
    field: pd.DataFrame | None,
    recs: list[str],
    sheets: list[Path],
    figures: dict[str, Path],
) -> Path:
    L: list[str] = []
    w = L.append
    rel = lambda p: Path(p).relative_to(out_dir).as_posix()  # noqa: E731

    w("# RockID dataset audit\n")
    w(f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · dataset `{cfg_dict['kaggle_dataset']}`\n")

    w("## Summary\n")
    for k, v in summary.items():
        w(f"- **{k}:** {v}")
    w("")

    w("## License\n")
    if license_info:
        names = ", ".join(l.get("name", "?") for l in license_info.get("licenses", [])) or "not stated"
        w(f"- Kaggle license field: **{names}**")
        if license_info.get("title"):
            w(f"- Title: {license_info['title']}")
    else:
        w("- Kaggle metadata could not be read. Check the dataset page by hand.")
    w(f"\n{TRAINING_ONLY_POLICY}\n")

    w("## Label source\n")
    if cfg_dict.get("label_from") == "filename":
        w("Labels come from each file name (`100Andesite.png` → `andesite`). The parent folder is kept as the `family` "
          "column. Pre-made split folders (train/test/valid) are ignored, because we re-split.\n")
    else:
        w("Labels come from each image's parent folder name, slugified. Pre-made split folders (train/test/valid) are ignored, because we re-split.\n")
    if label_files:
        w(f"Label-like files found in the dataset ({len(label_files)}). Check that none of them changes the labels: " + ", ".join(f"`{f}`" for f in label_files[:15]) + "\n")
    multi = {k: v for k, v in merged_raw_names.items() if len(v) > 1}
    if multi:
        w("Folder names that collapsed into one class (check these are really the same class):\n")
        for k, v in multi.items():
            w(f"- `{k}` ← {', '.join(v)}")
        w("")

    w("## Classes\n")
    w(f"![class counts]({rel(figures['class_counts'])})\n")
    cols = [c for c in ["family", "raw_names", "total", "clean", "train", "val", "test", "exact_duplicate", "cross_class_duplicate",
                        "decode_error", "too_small", "plain_bg_share", "blurry_share", "probe_recall", "nearest_class", "nearest_sim", "status"] if c in t]
    w(md_table(t[cols].rename_axis("class")))
    w("")

    w("## Duplicates\n")
    for k, v in dup_stats.items():
        w(f"- {k}: {v}")
    w("\nNear-duplicates are grouped into clusters; a cluster always lands in a single split. Exact copies keep one image.\n")

    w("## Quality\n")
    w(f"![blur]({rel(figures['blur'])})\n")
    w(f"![short side]({rel(figures['short_side'])})\n")

    w("## Background bias\n")
    w(f"![plain background share]({rel(figures['plain_bg'])})\n")
    w("Share of images per class whose border is nearly one color (studio or plain-backdrop shots). This is a heuristic; the contact sheets show what it means in practice.\n")
    if bg_probe is not None:
        w(f"Background-only linear probe (center {int(0.7*100)}% hidden): top-1 **{pct(bg_probe['top1'])}** vs chance {pct(bg_probe['chance'])}.\n")

    if probe is not None:
        w("## Linear probe (frozen MobileNetV2 features, 5-fold group CV)\n")
        w(f"- top-1 **{pct(probe['top1'])}**, top-3 **{pct(probe['top3'])}**, chance {pct(probe['chance'])}, majority class {pct(probe['majority'])}")
        w("- A rough floor for fine-tuning, not a forecast of the final score.\n")
        if confused is not None and len(confused):
            w("Most frequent confusions (share of the true class):\n")
            w(md_table(confused, index=False))
            w("")

    w("## Field test set\n")
    if field is None or field.empty:
        w("No field set found. Add real-world photos to `MyDrive/RockID/field_test/<class>/` (10–20 per class) before Phase 2: the gate needs them.\n")
    else:
        usable = field[~field["leaks_into_dataset"] & field["known_class"]]
        w(f"- {len(field)} images, {len(usable)} usable · {int(field['leaks_into_dataset'].sum())} also appear in the dataset (excluded) · "
          f"{int((~field['known_class']).sum())} have a class the model won't know")
        w(md_table(usable.groupby("label_final").size().rename("images").to_frame().rename_axis("class")))
        w("")

    w("## Recommendations\n")
    for r in recs or ["No issues flagged."]:
        w(f"- {r}")
    w("")

    w("## Review before approving the class list\n")
    w("Contact sheets are in `review/`. **Do not commit `review/`**: it contains dataset images.\n")
    for s in sheets:
        w(f"- `{rel(s)}`")
    w("\nTo merge or drop classes, set `class_merges` / `drop_classes` in the notebook config and re-run from the split step.\n")

    w("## Config\n")
    w("```json\n" + json.dumps(cfg_dict, indent=2) + "\n```\n")

    path = out_dir / "audit.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path
