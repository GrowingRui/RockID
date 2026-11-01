from __future__ import annotations

import hashlib
import os
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image, ImageOps

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}

# Allow large photos but keep a guard against decompression bombs.
Image.MAX_IMAGE_PIXELS = 100_000_000

_GRAY = np.array([0.299, 0.587, 0.114], dtype=np.float32)


def load_rgb(path: str | os.PathLike, max_side: int | None = None) -> Image.Image:
    """Decode an image as RGB, applying EXIF orientation and flattening transparency onto white."""
    with Image.open(path) as raw:
        im = ImageOps.exif_transpose(raw)
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            im = Image.new("RGB", rgba.size, (255, 255, 255))
            im.paste(rgba, mask=rgba.getchannel("A"))
        else:
            im = im.convert("RGB")
    if max_side and max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.BILINEAR)
    return im


def laplacian_var(gray: np.ndarray) -> float:
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0
    lap = (
        gray[1:-1, :-2] + gray[1:-1, 2:] + gray[:-2, 1:-1] + gray[2:, 1:-1] - 4.0 * gray[1:-1, 1:-1]
    )
    return float(lap.var())


def border_plain_fraction(rgb: np.ndarray, border_frac: float = 0.08, tol: float = 24.0) -> float:
    """Share of border pixels within `tol` of the border's median color (1.0 = perfectly plain)."""
    h, w, _ = rgb.shape
    bh, bw = max(1, int(h * border_frac)), max(1, int(w * border_frac))
    mask = np.zeros((h, w), dtype=bool)
    mask[:bh] = mask[-bh:] = True
    mask[:, :bw] = mask[:, -bw:] = True
    px = rgb[mask]
    dist = np.linalg.norm(px - np.median(px, axis=0), axis=1)
    return float((dist <= tol).mean())


def analyze_image(path: str | os.PathLike, plain_tol: float = 24.0) -> dict:
    """Per-image quality and hashing stats. Never raises; failures are reported in `decode_error`."""
    rec: dict = {"decode_error": None}
    try:
        with Image.open(path) as raw:
            rec["format"] = raw.format
            rec["orig_mode"] = raw.mode
            rec["n_frames"] = getattr(raw, "n_frames", 1)
        im = load_rgb(path)
    except Exception as e:  # corrupt, truncated or unsupported files
        rec["decode_error"] = f"{type(e).__name__}: {e}"[:200]
        return rec

    w, h = im.size
    full = np.asarray(im)
    small = im.copy()
    small.thumbnail((512, 512), Image.BILINEAR)
    s = np.asarray(small, dtype=np.float32)
    gray = s @ _GRAY

    rec.update(
        width=w,
        height=h,
        pixel_sha256=hashlib.sha256(f"{w}x{h}".encode() + full.tobytes()).hexdigest(),
        phash=str(imagehash.phash(small)),
        blur_var=laplacian_var(gray),
        brightness=float(gray.mean()),
        grayscale=bool(
            np.abs(s[..., 0] - s[..., 1]).mean() < 3 and np.abs(s[..., 1] - s[..., 2]).mean() < 3
        ),
        border_plain_frac=border_plain_fraction(s, tol=plain_tol),
    )
    return rec


def is_image_file(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in IMAGE_EXTS


_DIHEDRAL = [
    [Image.Transpose.ROTATE_90], [Image.Transpose.ROTATE_180], [Image.Transpose.ROTATE_270],
    [Image.Transpose.FLIP_LEFT_RIGHT], [Image.Transpose.FLIP_LEFT_RIGHT, Image.Transpose.ROTATE_90],
    [Image.Transpose.FLIP_LEFT_RIGHT, Image.Transpose.ROTATE_180], [Image.Transpose.FLIP_LEFT_RIGHT, Image.Transpose.ROTATE_270],
]


def dihedral_phashes(path: str | os.PathLike) -> list[str]:
    """pHash of the 7 rotated/mirrored versions of an image (same 512 px basis as `analyze_image`).
    Re-uploaded datasets often contain flipped or rotated copies that a plain pHash misses."""
    small = load_rgb(path)
    small.thumbnail((512, 512), Image.BILINEAR)
    out = []
    for ops in _DIHEDRAL:
        im = small
        for op in ops:
            im = im.transpose(op)
        out.append(str(imagehash.phash(im)))
    return out
