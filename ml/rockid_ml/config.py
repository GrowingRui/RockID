from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class AuditConfig:
    kaggle_dataset: str = "kutlayusta/type-of-rocks-and-minerals-dataset"
    seed: int = 42
    # "folder": class = parent folder. "filename": class = name in the file (e.g. 100Andesite.png),
    # parent folder kept as `family`. This dataset's folders only hold igneous/metamorphic/sedimentary.
    label_from: str = "filename"

    # Splits (fractions of clean images; the rest is train)
    val_frac: float = 0.15
    test_frac: float = 0.15

    # Class health
    min_images_per_class: int = 150
    min_side: int = 64  # images smaller than this on their short side are excluded

    # Duplicate detection. Over-grouping only costs split balance, under-grouping leaks,
    # so both signals are joined with OR.
    phash_max_dist: int = 6  # Hamming distance on the 64-bit perceptual hash
    emb_min_sim: float = 0.95  # cosine similarity of MobileNetV2 embeddings

    # Background bias heuristic: share of border pixels close to the border's median color
    plain_tol: float = 24.0  # RGB distance counted as "same color"
    plain_frac_threshold: float = 0.85  # image counts as plain background at or above this
    studio_class_warn: float = 0.80  # warn when a class has more plain-background images than this

    blur_low: float = 50.0  # Laplacian variance (on a 512 px grayscale copy) below this is blurry

    exclude_cross_class: bool = True  # drop duplicate clusters that carry more than one label

    # Filled in after reviewing the first audit run, then re-run the split step
    class_merges: dict[str, str] = field(default_factory=dict)  # {"old-slug": "target-slug"}
    drop_classes: list[str] = field(default_factory=list)
    keep_below_min: list[str] = field(default_factory=list)  # deliberate exceptions to the minimum

    background_probe: bool = True
    embed_size: int = 224

    def to_dict(self) -> dict:
        return asdict(self)
