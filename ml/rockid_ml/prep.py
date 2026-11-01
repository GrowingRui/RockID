"""Image preparation for training: one decode pass that also proves the dataset matches the manifest.

Training reads small JPEG copies (short side `short_side` px) instead of the raw files, so each epoch
decodes ~30 KB per image instead of multi-megapixel PNGs. `client_preprocess` is the reference
version of what the web/mobile clients do (center square crop, bilinear resize, RGB uint8); test and
field evaluation use it so the reported numbers match what users get."""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from tqdm.auto import tqdm

from .images import load_rgb


def pixel_sha256(im: Image.Image) -> str:
    """Same fingerprint as the audit (`images.analyze_image`): size + decoded RGB bytes."""
    w, h = im.size
    return hashlib.sha256(f"{w}x{h}".encode() + np.asarray(im).tobytes()).hexdigest()


def shrink(im: Image.Image, short_side: int) -> Image.Image:
    """Downscale so the short side is `short_side` px (never upscales)."""
    w, h = im.size
    s = short_side / min(w, h)
    if s >= 1:
        return im
    return im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.BILINEAR)


def center_square(im: Image.Image) -> Image.Image:
    w, h = im.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    return im.crop((left, top, left + side, top + side))


def client_preprocess(path: str | os.PathLike, size: int = 224) -> np.ndarray:
    """Reference client path: decode (EXIF orientation, alpha on white) → center square → bilinear → uint8 HWC RGB."""
    return np.asarray(center_square(load_rgb(path)).resize((size, size), Image.BILINEAR), dtype=np.uint8)


def prep_name(rel_path: str) -> str:
    return str(Path(rel_path).with_suffix(".jpg"))


def _prep_one(src: Path, dst: Path, short_side: int, quality: int) -> str:
    im = load_rgb(src)
    sha = pixel_sha256(im)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shrink(im, short_side).save(dst, quality=quality)
    return sha


def prepare_images(
    manifest: pd.DataFrame,
    raw_root: str | Path,
    out_root: str | Path,
    short_side: int = 288,
    quality: int = 95,
    workers: int = 8,
) -> pd.DataFrame:
    """Writes `out_root/<rel_path>.jpg` for every manifest row and checks each image's pixel SHA-256.
    Returns the manifest with `prep_path` and `sha_ok`; images already prepared are skipped (sha_ok = NA)."""
    raw_root, out_root = Path(raw_root), Path(out_root)
    m = manifest.copy()
    m["prep_path"] = [str(out_root / prep_name(p)) for p in m["rel_path"]]
    todo = [i for i, p in enumerate(m["prep_path"]) if not Path(p).exists()]
    sha_ok = pd.Series(pd.NA, index=m.index, dtype="boolean")
    if todo:
        def work(i: int) -> str:
            r = m.iloc[i]
            return _prep_one(raw_root / r["rel_path"], Path(r["prep_path"]), short_side, quality)

        with ThreadPoolExecutor(workers) as ex:
            shas = list(tqdm(ex.map(work, todo), total=len(todo), desc="prep"))
        sha_ok.iloc[todo] = np.asarray(shas) == m["pixel_sha256"].iloc[todo].to_numpy()
    m["sha_ok"] = sha_ok
    return m
