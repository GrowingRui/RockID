"""Photo sources for the stone dataset: Kaggle, Roboflow Universe and Wikimedia Commons.

Every fetcher writes images under `<root>/<source>/<original class>/<file>` and returns an inventory
(one row per image: rel_path, source, source_class, license, author, url). Matching original class
names to our stones is separate (`build_matcher`/`match_stone`), so unmatched names can be reported
instead of guessed. Images stay training/evaluation data; only Commons images carry licenses that
allow showing them (with credit)."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from .images import is_image_file

INVENTORY_COLS = ["rel_path", "source", "source_class", "license", "author", "url"]
SPLIT_DIRS = {"train", "test", "valid", "validation", "val"}
USER_AGENT = "RockID-dataset-audit/0.1 (https://github.com/GrowingRui/RockID)"


# ---------------------------------------------------------------- name matching

# Generic words that don't change which stone it is. "crystal" stays meaningful ("rock crystal" ≠ "rock").
_NOISE = {"stone", "stones", "gem", "gems", "gemstone", "gemstones", "the", "tumbled", "polished"}


def name_key(name: str) -> frozenset[str]:
    """Order-, case- and punctuation-insensitive words: "Quartz Rose", "rose_quartz" and "Rose-Quartz" are equal.
    Apostrophes are dropped (tiger's → tigers); generic words like "stone" or "tumbled" are ignored."""
    s = name.lower().replace("'", "").replace("’", "")
    words = set(re.findall(r"[a-z0-9]+", s)) - _NOISE
    return frozenset(words)


def build_matcher(stones: list[dict]) -> dict[frozenset[str], str]:
    m: dict[frozenset[str], str] = {}
    for s in stones:
        for n in [s["slug"], s["name"], *s.get("aliases", [])]:
            k = name_key(n)
            if k in m and m[k] != s["slug"]:
                raise ValueError(f"alias {n!r} is used by both {m[k]} and {s['slug']}")
            m[k] = s["slug"]
    return m


def match_stone(source_class: str, matcher: dict[frozenset[str], str]) -> str | None:
    k = name_key(source_class)
    return matcher.get(k) if k else None


# ---------------------------------------------------------------- helpers

def _inventory_from_folders(root: Path, source_dir: Path, source: str, license_: str, url: str) -> pd.DataFrame:
    """One row per image; the class is the nearest parent folder that isn't a split folder."""
    rows = []
    for p in sorted(source_dir.rglob("*")):
        if not is_image_file(p):
            continue
        parents = [d for d in p.relative_to(source_dir).parts[:-1] if d.lower() not in SPLIT_DIRS]
        if not parents:
            continue
        rows.append({"rel_path": p.relative_to(root).as_posix(), "source": source, "source_class": parents[-1],
                     "license": license_, "author": None, "url": url})
    return pd.DataFrame(rows, columns=INVENTORY_COLS)


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]


# ---------------------------------------------------------------- Kaggle

def fetch_kaggle(dataset: str, root: Path) -> pd.DataFrame:
    """Downloads with the kaggle CLI (credentials from the environment). Class = folder name."""
    source = "kaggle-" + dataset.split("/")[-1]
    dest = root / source
    if not dest.exists():
        tmp = root / (source + ".partial")
        shutil.rmtree(tmp, ignore_errors=True)
        subprocess.run(["kaggle", "datasets", "download", "-d", dataset, "-p", str(tmp), "--unzip"], check=True)
        tmp.rename(dest)
    return _inventory_from_folders(root, dest, source, "see Kaggle page (training/evaluation only)",
                                   f"https://www.kaggle.com/datasets/{dataset}")


# ---------------------------------------------------------------- Roboflow Universe

def roboflow_info(api_key: str, workspace: str, project: str) -> dict:
    url = f"https://api.roboflow.com/{workspace}/{project}?" + urllib.parse.urlencode({"api_key": api_key})
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def _latest_version(info: dict) -> int:
    nums = [int(str(v.get("id", "")).rsplit("/", 1)[-1]) for v in info.get("versions", []) if str(v.get("id", "")).rsplit("/", 1)[-1].isdigit()]
    if not nums:
        raise RuntimeError("project has no downloadable version")
    return max(nums)


def _crop_coco(split_dir: Path, out: Path, pad: float = 0.1) -> int:
    """Object-detection export → one cropped image per box, in a folder named after the box's class."""
    from PIL import Image

    ann = json.loads((split_dir / "_annotations.coco.json").read_text())
    cats = {c["id"]: c["name"] for c in ann["categories"]}
    files = {i["id"]: i["file_name"] for i in ann["images"]}
    n = 0
    for k, a in enumerate(ann["annotations"]):
        x, y, w, h = a["bbox"]
        if w < 16 or h < 16:
            continue
        with Image.open(split_dir / files[a["image_id"]]) as im:
            W, H = im.size
            px, py = w * pad, h * pad
            box = (max(0, x - px), max(0, y - py), min(W, x + w + px), min(H, y + h + py))
            d = out / cats[a["category_id"]]
            d.mkdir(parents=True, exist_ok=True)
            im.convert("RGB").crop(box).save(d / f"{Path(files[a['image_id']]).stem}_{k}.jpg", quality=95)
            n += 1
    return n


def fetch_roboflow(api_key: str, slug: str, root: Path) -> tuple[pd.DataFrame, dict]:
    """`slug` = "workspace/project". Classification projects download as class folders; detection
    projects are cropped to one image per box. Returns (inventory, project facts for the report)."""
    workspace, project = slug.split("/")
    info = roboflow_info(api_key, workspace, project)
    p = info.get("project", {})
    version = _latest_version(info)
    facts = {"project": slug, "type": p.get("type"), "images": p.get("images"), "version": version,
             "license": p.get("license") or "see Universe page", "classes": p.get("classes")}
    source = "roboflow-" + project
    dest = root / source
    if not dest.exists():
        from roboflow import Roboflow

        tmp = root / (source + ".download")
        shutil.rmtree(tmp, ignore_errors=True)
        v = Roboflow(api_key=api_key).workspace(workspace).project(project).version(version)
        if p.get("type") == "classification":
            v.download("folder", location=str(tmp), overwrite=True)
            shutil.move(str(tmp), str(dest))
        else:
            v.download("coco", location=str(tmp), overwrite=True)
            staging = root / (source + ".partial")
            shutil.rmtree(staging, ignore_errors=True)
            for split in tmp.iterdir():
                if (split / "_annotations.coco.json").exists():
                    _crop_coco(split, staging)
            staging.rename(dest)
            shutil.rmtree(tmp, ignore_errors=True)
    inv = _inventory_from_folders(root, dest, source, facts["license"],
                                  f"https://universe.roboflow.com/{workspace}/{project}")
    return inv, facts


# ---------------------------------------------------------------- Wikimedia Commons

def _commons(params: dict, retries: int = 3) -> dict:
    params = {**params, "format": "json"}
    req = urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    return {}


def _resolve_category(cat: str) -> str:
    """Follows {{Category redirect|X}} and {{seecat|X}} (e.g. Amethyst → Amethysts)."""
    for _ in range(3):
        d = _commons({"action": "parse", "page": f"Category:{cat}", "prop": "wikitext"})
        text = d.get("parse", {}).get("wikitext", {}).get("*", "")
        m = re.search(r"\{\{\s*(?:category redirect|seecat)\s*\|\s*(?:Category:)?([^}|]+)", text, re.I)
        if not m:
            return cat
        cat = m.group(1).strip()
    return cat


def _members(cat: str, kind: str) -> list[str]:
    out, cont = [], {}
    while True:
        d = _commons({"action": "query", "list": "categorymembers", "cmtitle": f"Category:{cat}",
                      "cmtype": kind, "cmlimit": 500, **cont})
        out += [m["title"] for m in d.get("query", {}).get("categorymembers", [])]
        if "continue" not in d:
            return out
        cont = {"cmcontinue": d["continue"]["cmcontinue"]}


def commons_file_titles(categories: list[str], exclude_subcats: str, limit: int) -> list[str]:
    """Files directly in the categories plus one level of subcategories (minus excluded ones), sorted, capped."""
    titles: set[str] = set()
    for cat in categories:
        cat = _resolve_category(cat)
        titles.update(_members(cat, "file"))
        for sub in _members(cat, "subcat"):
            name = sub.split(":", 1)[1]
            if not re.search(exclude_subcats, name):
                titles.update(_members(name, "file"))
    return sorted(titles)[:limit]


def _strip_html(s: str | None) -> str | None:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip() if s else None


def commons_image_info(titles: list[str], width: int = 800) -> list[dict]:
    rows = []
    for i in range(0, len(titles), 50):
        d = _commons({"action": "query", "titles": "|".join(titles[i:i + 50]), "prop": "imageinfo",
                      "iiprop": "url|mime|size|extmetadata", "iiurlwidth": width})
        for page in d.get("query", {}).get("pages", {}).values():
            ii = (page.get("imageinfo") or [{}])[0]
            meta = ii.get("extmetadata", {})
            rows.append({
                "title": page.get("title"), "mime": ii.get("mime"), "width": ii.get("width"), "height": ii.get("height"),
                "thumb": ii.get("thumburl") or ii.get("url"), "page": ii.get("descriptionurl"),
                "license": (meta.get("LicenseShortName") or {}).get("value"),
                "author": _strip_html((meta.get("Artist") or {}).get("value")),
            })
    return rows


def keep_commons_image(r: dict, min_side: int = 300) -> bool:
    return r.get("mime") in ("image/jpeg", "image/png") and min(r.get("width") or 0, r.get("height") or 0) >= min_side \
        and bool(r.get("license")) and bool(r.get("thumb"))


def fetch_commons(stones: list[dict], root: Path, per_stone: int, exclude_subcats: str, workers: int = 4) -> pd.DataFrame:
    """Downloads ≤ `per_stone` images per stone (800 px thumbnails) with author and license."""
    source = "commons"
    rows = []
    for s in stones:
        titles = commons_file_titles(s.get("commons_categories", []), exclude_subcats, per_stone * 2)
        info = [r for r in commons_image_info(titles) if keep_commons_image(r)][:per_stone]
        d = root / source / s["slug"]
        d.mkdir(parents=True, exist_ok=True)

        def get(r):
            f = d / (_safe(r["title"].split(":", 1)[1].rsplit(".", 1)[0]) + (".png" if r["mime"] == "image/png" else ".jpg"))
            if not f.exists():
                req = urllib.request.Request(r["thumb"], headers={"User-Agent": USER_AGENT})
                try:
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        f.write_bytes(resp.read())
                except Exception:
                    return None
            return {"rel_path": f.relative_to(root).as_posix(), "source": source, "source_class": s["slug"],
                    "license": r["license"], "author": r["author"], "url": r["page"]}

        with ThreadPoolExecutor(workers) as ex:
            rows += [x for x in ex.map(get, info) if x]
    return pd.DataFrame(rows, columns=INVENTORY_COLS)


# ---------------------------------------------------------------- combine

def label_inventory(inv: pd.DataFrame, stones: list[dict]) -> pd.DataFrame:
    """Adds `label` (stone slug or None). Commons rows are already per stone."""
    m = build_matcher(stones)
    inv = inv.copy()
    inv["label"] = [sc if src == "commons" else match_stone(sc, m) for src, sc in zip(inv["source"], inv["source_class"])]
    return inv


def class_overview(inv: pd.DataFrame) -> pd.DataFrame:
    """Every (source, original class) with its image count and the stone it maps to (empty = unmatched)."""
    return (inv.groupby(["source", "source_class"], dropna=False)
               .agg(images=("rel_path", "size"), stone=("label", "first"))
               .reset_index().sort_values(["stone", "source", "images"], ascending=[True, True, False], na_position="last"))
