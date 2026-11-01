"""Stone name matching and source inventories (offline)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from rockid_ml import sources

STONES = json.loads((Path(__file__).parents[1] / "configs" / "stones_v1.json").read_text(encoding="utf-8"))["stones"]


@pytest.fixture(scope="module")
def matcher():
    return sources.build_matcher(STONES)


@pytest.mark.parametrize("name,slug", [
    ("Quartz Rose", "rose-quartz"), ("rose_quartz", "rose-quartz"), ("Rose-Quartz", "rose-quartz"),
    ("Tigers Eye", "tigers-eye"), ("tiger's eye", "tigers-eye"), ("Tiger Eye", "tigers-eye"),
    ("Lapis Lazuli", "lapis-lazuli"), ("Quartz Smoky", "smoky-quartz"), ("Rock Crystal", "clear-quartz"),
    ("Amethyst", "amethyst"), ("tumbled amethyst", "amethyst"), ("Aventurine Green", "green-aventurine"),
    ("Schorl", "black-tourmaline"), ("Obsidian", "black-obsidian"), ("Haematite", "hematite"),
])
def test_matches(matcher, name, slug):
    assert sources.match_stone(name, matcher) == slug


@pytest.mark.parametrize("name", ["Rock", "Tourmaline", "Snowflake Obsidian", "Quartz Rutilated", "Aventurine Yellow",
                                  "Crystal", "Stone", "Sapphire Blue", ""])
def test_does_not_guess(matcher, name):
    assert sources.match_stone(name, matcher) is None


def test_alias_conflict_is_an_error():
    with pytest.raises(ValueError):
        sources.build_matcher([{"slug": "a", "name": "Quartz"}, {"slug": "b", "name": "B", "aliases": ["quartz"]}])


def test_inventory_skips_split_folders(tmp_path):
    for rel in ["src/train/Quartz Rose/a.jpg", "src/test/Quartz Rose/b.jpg", "src/valid/Amethyst/c.png", "src/loose.jpg"]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.zeros((8, 8, 3), np.uint8)).save(p)
    inv = sources._inventory_from_folders(tmp_path, tmp_path / "src", "src", "lic", "url")
    assert sorted(inv["source_class"]) == ["Amethyst", "Quartz Rose", "Quartz Rose"]
    labeled = sources.label_inventory(inv, STONES)
    assert set(labeled["label"]) == {"amethyst", "rose-quartz"}
    ov = sources.class_overview(labeled)
    assert ov.set_index("source_class").loc["Quartz Rose", "images"] == 2


def test_keep_commons_image():
    ok = {"mime": "image/jpeg", "width": 800, "height": 600, "license": "CC BY-SA 4.0", "thumb": "u"}
    assert sources.keep_commons_image(ok)
    assert not sources.keep_commons_image({**ok, "mime": "image/svg+xml"})
    assert not sources.keep_commons_image({**ok, "height": 200})
    assert not sources.keep_commons_image({**ok, "license": None})


def test_dihedral_pairs_find_rotated_and_mirrored_copies(tmp_path):
    from rockid_ml import dedup, images

    rng = np.random.default_rng(0)
    base = Image.fromarray(rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)).resize((256, 192), Image.BICUBIC)
    other = Image.fromarray(rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)).resize((256, 192), Image.BICUBIC)
    files = {"a.png": base, "a_rot.png": base.transpose(Image.Transpose.ROTATE_90),
             "a_flip.png": base.transpose(Image.Transpose.FLIP_LEFT_RIGHT), "b.png": other}
    for n, im in files.items():
        im.save(tmp_path / n)
    names = list(files)
    orig = [images.analyze_image(tmp_path / n)["phash"] for n in names]
    plain = dedup.hamming_pairs(dedup.phash_to_uint64(orig), 6)
    assert len(plain) == 0  # a plain pHash misses all of them
    pairs = dedup.dihedral_pairs(orig, [images.dihedral_phashes(tmp_path / n) for n in names], 6)
    found = {(names[i], names[j]) for i, j in zip(pairs["i"], pairs["j"])}
    assert ("a.png", "a_rot.png") in found and ("a.png", "a_flip.png") in found
    assert not any("b.png" in p for p in found)
