# RockID ML

Python pipeline for the rock/mineral classifier. Runs on **Google Colab** (free T4 GPU).
Not part of the pnpm workspace.

| Path | Contents |
|---|---|
| `rockid_ml/` | Reusable pipeline code; notebooks only call it |
| `notebooks/01_audit.ipynb` | Phase 1: dataset audit and splits |
| `splits/` | Committed split manifests (rebuild the exact splits from the raw dataset) |
| `reports/` | Audit and evaluation reports (markdown + charts only, never dataset images) |
| `tests/` | pytest suite, runs locally on synthetic images |

## Phase 1: run the audit

1. Do the Phase 1 items in [../docs/phase-0-setup.md](../docs/phase-0-setup.md) (Kaggle secrets, code location).
2. Open `notebooks/01_audit.ipynb` in Colab (*File → Upload notebook*, or *File → Open notebook → GitHub*).
3. *Runtime → Change runtime type → T4 GPU*, then *Runtime → Run all*.
4. Read `MyDrive/RockID/audit/<timestamp>/audit.md` and the `review/` contact sheets.
5. Set `CLASS_MERGES` / `DROP_CLASSES` in step 8 and re-run from there until the class list looks right.
6. Step 13 downloads a zip. Unzip it into this `ml/` folder: it adds `reports/audit-<timestamp>/` and `splits/`.

The first run downloads the dataset and computes stats and embeddings (roughly tens of minutes,
depending on dataset size). Everything is cached in `MyDrive/RockID/cache/`, so re-runs take minutes.

### What the audit does
- **Labels** come from the parent folder name, slugified. Pre-made `train/test/valid` folders are ignored because we re-split.
- **Exact duplicates:** SHA-256 of decoded pixels; one copy is kept.
- **Near-duplicates:** perceptual hash (Hamming ≤ 6) **or** MobileNetV2 embedding cosine ≥ 0.95,
  joined into clusters. A cluster always lands in a single split, so near-copies can't leak from train into test.
- **Cross-class duplicates** (same image under two labels) are excluded until reviewed.
- **Quality:** decode errors, small images (< 64 px short side), blur score.
- **Background bias:** border-uniformity heuristic per class, plus a *background-only probe*
  (classifier trained with the specimen hidden). High accuracy there means the model could learn backgrounds instead of rocks.
- **Linear probe:** logistic regression on frozen features, a cheap early read on separability and on which classes get confused.
- **Splits:** 70/15/15, stratified by class, grouped by cluster, seed 42.
- **Field set:** your own photos, checked for overlap with the dataset.

## Local tests

```bash
cd ml
python -m venv .venv && .venv/Scripts/activate   # Windows; use .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
pytest
```
