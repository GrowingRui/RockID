# RockID ML

Python pipeline for the rock/mineral classifier. Runs on **Google Colab** (free T4 GPU).
Not part of the pnpm workspace.

| Path | Contents |
|---|---|
| `rockid_ml/` | Reusable pipeline code; notebooks only call it |
| `notebooks/01_audit.ipynb` | Phase 1: dataset audit and splits |
| `notebooks/02_train.ipynb` | Phase 2: TF.js smoke test, then two-stage training |
| `notebooks/03_evaluate.ipynb` | Phase 2: calibration, test + field scores, go/no-go gate |
| `configs/` | Versioned class lists (`classes_vN.json`) and training configs (`train_vN.json`); current: `classes_v2` + `train_v3` |
| `scripts/` | Small helpers the notebooks run (Node TF.js check) |
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

## Phase 2: train

1. Open `notebooks/02_train.ipynb` in Colab with a T4 GPU runtime.
2. First run: set `SMOKE_TEST_ONLY = True` and *Run all*. Step 4 exports an untrained model to TF.js
   (converter installed with `--no-deps`, so it cannot replace Colab's TensorFlow), runs it in Node and compares it with Keras. It must pass before training;
   the working versions land in `MyDrive/RockID/runs/<run_name>/versions.json`.
3. Set `SMOKE_TEST_ONLY = False` and *Run all*. A disconnect is fine: re-run and it resumes the current stage.
4. Step 9 downloads a zip. Unzip it into `ml/`: it adds `reports/train-<run_name>/`.

What the training does:
- Settings come from `configs/train_v1.json`. Changing anything means a new `run_name`; the notebook
  refuses to resume a run folder with a different config.
- Images are decoded once with the audit's loader and **checked against the manifest's pixel SHA-256**,
  then cached as 288 px JPEGs (`MyDrive/RockID/cache/prep_288.zip`).
- MobileNetV2 (ImageNet), raw RGB 0–255 in, normalization in the graph, **logits** out
  (softmax + temperature are added at export). Stage 1: frozen backbone, Adam 1e-3. Stage 2: top 30 %
  unfrozen with BatchNorm frozen, Adam 1e-5. Early stopping on validation top-1; the best epoch is kept.
- Class weights (inverse frequency), label smoothing 0.1, random crops, flips, 90° turns, mild color jitter.
- Only validation is used. Test set, field set, calibration and the gate: `03_evaluate`.
- TF.js weights are fp16 (≈4.4 MB): uint8 was measured too lossy for MobileNetV2 ([ADR 0002](../docs/adr/0002-tfjs-fp16-weights.md)).

## Phase 2: evaluate and gate

1. Put 10–20 real-world photos per class in `MyDrive/RockID/field_test/<class>/` (folder names may use
   merged names, e.g. `flint/` counts as `chert`). The gate can't pass without a field set.
2. Open `notebooks/03_evaluate.ipynb` and *Run all*.
3. Step 7 downloads a zip; unzip it into `ml/` (adds `reports/eval-<run_name>/`).

What it does:
- **Calibration** (validation only): a temperature for honest confidences, then the app's "uncertain" rule
  (top-1 < τ or top-1 − top-2 < margin), picked for the largest share of confident answers that are still
  `TARGET_CONFIDENT_ACC` (default 90 %) correct.
- **Test set** scored once, preprocessed like the app (`prep.client_preprocess`: center square, bilinear).
- **Field set** scored without near-copies of dataset images.
- **Gate** (ADR 0003): test top-1 ≥ 60 %, top-3 ≥ 80 %, field top-3 ≥ 65 %, every class recall ≥ 40 %. A failed gate
  lists each weak class and where its images go (merge/data/drop candidates).
- **Parity set**: 50 test images with their reference top-3 (`golden_set.csv`) for Phases 3 and 6.

## Local tests

```bash
cd ml
python -m venv .venv && .venv/Scripts/activate   # Windows; use .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
pip install tensorflow-cpu   # optional: also runs the TF pipeline/model tests
pytest
```
