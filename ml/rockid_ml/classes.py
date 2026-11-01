"""Versioned class list: merges, drops and display names (ml/configs/classes_vN.json)."""

from __future__ import annotations

import json
from pathlib import Path


def load_class_config(path: str | Path) -> dict:
    cc = json.loads(Path(path).read_text(encoding="utf-8"))
    cc.setdefault("merges", {})
    cc.setdefault("drop", [])
    cc.setdefault("keep_below_min", [])
    cc.setdefault("display_names", {})
    return cc


def validate_class_config(cc: dict, labels: set[str]) -> list[str]:
    """Problems that would silently do nothing or contradict each other (typos, merge into a dropped class)."""
    problems = []
    for src in cc["merges"]:
        if src not in labels:
            problems.append(f"merge source `{src}` is not a dataset class")
    for name in cc["drop"]:
        if name not in labels:
            problems.append(f"drop `{name}` is not a dataset class")
    targets = set(cc["merges"].values())
    for t in targets & set(cc["drop"]):
        problems.append(f"`{t}` is both a merge target and dropped")
    for src, dst in cc["merges"].items():
        if dst in cc["merges"]:
            problems.append(f"chained merge `{src}` -> `{dst}` -> `{cc['merges'][dst]}`; point it at the final class")
    return problems


def final_classes(cc: dict, labels: set[str]) -> list[str]:
    merged = {cc["merges"].get(l, l) for l in labels}
    return sorted(merged - set(cc["drop"]))
