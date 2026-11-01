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
