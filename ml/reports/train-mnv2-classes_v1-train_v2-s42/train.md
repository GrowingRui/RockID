# RockID training run `mnv2-classes_v1-train_v2-s42`

Generated 2026-11-01 12:09 UTC

## Summary

- **Data:** 8,277 images, 29 classes (splits/split_manifest_classes_v1.csv, class list v1)
- **Splits:** train 5,809 · val 1,233 · test 1,235 (test not used here)
- **Model:** mobilenet_v2 α 1.0, 224 px, logits output, in-graph normalization
- **Stage 1:** 15 epochs, best epoch 8 (val_top1 0.375)
- **Stage 2:** 38 epochs, best epoch 30 (val_top1 0.427)
- **Training time (this session):** 25 min
- **TF.js smoke test:** passed · float16 · 4.43 MB · max |Δp| 0.0020
- **Versions:** {"python": "3.13.16", "tensorflow": "2.21.0", "keras": "3.13.2", "numpy": "2.1.3", "converter": {"tensorflowjs": "4.22.0", "installed": ["tensorflowjs==4.22.0"]}, "node": {"node": "v22.23.4", "tfjs_npm": "4.22.0"}}

## Validation (indicative)

The best epoch was picked on validation, so these numbers lean optimistic. The gate itself is checked on the test and field sets in `03_evaluate`.

| metric | val | gate target | met on val |
|---|---|---|---|
| top-1 | 42.7% | ≥ 75.0% | no |
| top-3 | 63.3% | ≥ 90.0% | no |
| lowest class recall (slate) | 9.5% | ≥ 50.0% | no |

![training curves](figures/history.png)
![val recall per class](figures/val_recall.png)

## Per-class validation recall

| index | recall | val_images | train_images | class_weight |
|---|---|---|---|---|
| slate | 0.10 | 21 | 77 | 2.60 |
| hornfels | 0.13 | 23 | 143 | 1.40 |
| andesite | 0.17 | 30 | 173 | 1.16 |
| mudstone | 0.18 | 74 | 428 | 0.47 |
| evaporite | 0.23 | 39 | 149 | 1.34 |
| amphibolite | 0.26 | 38 | 180 | 1.11 |
| chert | 0.28 | 39 | 146 | 1.37 |
| schist | 0.29 | 49 | 269 | 0.74 |
| phyllite | 0.29 | 41 | 168 | 1.19 |
| pyroxenite | 0.31 | 26 | 134 | 1.49 |
| marble | 0.31 | 26 | 117 | 1.71 |
| scoria | 0.32 | 28 | 132 | 1.52 |
| rhyolite | 0.32 | 37 | 206 | 0.97 |
| quartzite | 0.33 | 46 | 205 | 0.98 |
| conglomerate | 0.40 | 35 | 160 | 1.25 |
| eclogite | 0.43 | 30 | 191 | 1.05 |
| gabbro | 0.46 | 35 | 171 | 1.17 |
| granite | 0.46 | 74 | 328 | 0.61 |
| talc-carbonate | 0.46 | 39 | 172 | 1.16 |
| sandstone | 0.47 | 62 | 231 | 0.87 |
| gneiss | 0.50 | 72 | 346 | 0.58 |
| limestone | 0.52 | 84 | 353 | 0.57 |
| basalt | 0.55 | 55 | 192 | 1.04 |
| pegmatite | 0.59 | 46 | 193 | 1.04 |
| serpentinite | 0.61 | 54 | 197 | 1.02 |
| breccia | 0.64 | 33 | 183 | 1.09 |
| coal | 0.79 | 53 | 350 | 0.57 |
| obsidian | 0.83 | 6 | 41 | 4.89 |
| pumice | 0.89 | 38 | 174 | 1.15 |

## Most confused pairs (validation)

| true | pred | count | share_of_true |
|---|---|---|---|
| slate | coal | 5 | 0.24 |
| scoria | pumice | 6 | 0.21 |
| amphibolite | gneiss | 8 | 0.21 |
| obsidian | slate | 1 | 0.17 |
| sandstone | limestone | 10 | 0.16 |
| talc-carbonate | limestone | 6 | 0.15 |
| pyroxenite | gneiss | 4 | 0.15 |
| phyllite | gneiss | 6 | 0.15 |
| scoria | granite | 4 | 0.14 |
| andesite | limestone | 4 | 0.13 |
| amphibolite | granite | 5 | 0.13 |
| hornfels | coal | 3 | 0.13 |
| quartzite | sandstone | 6 | 0.13 |
| evaporite | talc-carbonate | 5 | 0.13 |
| evaporite | limestone | 5 | 0.13 |

## Config

```json
{
  "run_name": "mnv2-classes_v1-train_v2-s42",
  "split_manifest": "splits/split_manifest_classes_v1.csv",
  "class_file": "configs/classes_v1.json",
  "seed": 42,
  "arch": "mobilenet_v2",
  "alpha": 1.0,
  "image_size": 224,
  "prep_short_side": 288,
  "batch_size": 32,
  "dropout": 0.3,
  "label_smoothing": 0.1,
  "class_weight_power": 1.0,
  "crop_area_min": 0.5,
  "crop_aspect": [
    0.75,
    1.333
  ],
  "flips": true,
  "rot90": true,
  "brightness": 0.15,
  "contrast": 0.15,
  "saturation": 0.15,
  "hue": 0.02,
  "stage1_epochs": 15,
  "stage1_lr": 0.001,
  "unfreeze_frac": 0.6,
  "stage2_epochs": 40,
  "stage2_lr": 0.0001,
  "patience": 8,
  "monitor": "val_top1",
  "deterministic_ops": false,
  "tfjs_converter": "tensorflowjs==4.22.0",
  "tfjs_quantization": "float16",
  "tfjs_max_abs_diff": 0.02,
  "tfjs_npm": "@tensorflow/tfjs@4.22.0",
  "max_web_model_mb": 5.0
}
```
