from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Sequence

import numpy as np
from PIL import Image

from .images import load_rgb


def _load(path, size: int, variant: str, center_frac: float) -> np.ndarray:
    a = np.asarray(load_rgb(path).resize((size, size), Image.BILINEAR), dtype=np.float32)
    if variant == "border":
        # Hide the specimen, keep only the surroundings: measures how much the background
        # alone predicts the class. 127.5 maps to 0 after MobileNet preprocessing.
        a = a.copy()
        m = int(size * (1 - center_frac) / 2)
        a[m : size - m, m : size - m] = 127.5
    return a


def embed_paths(
    paths: Sequence[str],
    size: int = 224,
    batch_size: int = 64,
    variant: str = "full",
    center_frac: float = 0.7,
    workers: int = 8,
) -> np.ndarray:
    """L2-normalized MobileNetV2 (ImageNet) global-average-pooled features, shape (N, 1280).
    Only pass images that decoded successfully."""
    import tensorflow as tf
    from tqdm.auto import tqdm

    model = tf.keras.applications.MobileNetV2(
        include_top=False, weights="imagenet", pooling="avg", input_shape=(size, size, 3)
    )
    preprocess = tf.keras.applications.mobilenet_v2.preprocess_input
    out = np.zeros((len(paths), model.output_shape[-1]), dtype=np.float32)

    with ThreadPoolExecutor(workers) as pool:
        for start in tqdm(range(0, len(paths), batch_size), desc=f"embed[{variant}]"):
            chunk = paths[start : start + batch_size]
            batch = np.stack(list(pool.map(lambda p: _load(p, size, variant, center_frac), chunk)))
            out[start : start + len(chunk)] = np.asarray(model(preprocess(batch), training=False))

    out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-12)
    return out
