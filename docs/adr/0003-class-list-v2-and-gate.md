# ADR 0003 — Class list v2 (13 rocks) and a lower Phase 2 gate

Date: 2026-11-01 · Status: **accepted** (owner chose the 13-class option)

## Context
Two training runs on class list v1 (29 classes), MobileNetV2:

| run | val top-1 | val top-3 | train top-1 |
|---|---|---|---|
| `mnv2-classes_v1-s42` (train_v1) | 40.5 % | 61.3 % | ~42 % |
| `mnv2-classes_v1-train_v2-s42` (train_v2, stronger fine-tuning) | 42.7 % | 63.3 % | ~73 % |

The second run fits its training images but validation stays near 42 %: the limit is the data
(few, noisy, web-scraped images; ADR 0001), not the training settings. The original gate
(75 % / 90 %) is out of reach with 29 classes.

Re-scoring the train_v2 validation logits over smaller class lists (no retraining; classes chosen on the
same validation set, so these estimates lean optimistic):

| classes | val top-1 | val top-3 | lowest recall |
|---|---|---|---|
| 29 (v1) | 42.7 % | 63.3 % | 10 % |
| 20 most common hiker rocks | 50.9 % | 72.5 % | 14 % |
| **13 (v2)** | **64.2 %** | **85.4 %** | **50 %** |
| 10 (drops granite, sandstone, eclogite) | 75.0 % | 92.2 % | 62 % |

## Decision
1. **Class list v2** (`ml/configs/classes_v2.json`): basalt, breccia, coal, eclogite, gabbro, gneiss, granite,
   limestone, obsidian, pegmatite, pumice, sandstone, serpentinite. It keeps the rocks people find most
   (granite, basalt, sandstone, limestone); the 10-class list met the old gate but dropped granite and sandstone.
2. **Split** `ml/splits/split_manifest_classes_v2.csv` = the v1 manifest filtered to these classes
   (`classes.subset_manifest`): every image keeps its v1 split, so no cluster spans splits and the test set is still unseen.
3. **Gate** lowered, set *before* any test-set result, a few points under the optimistic validation estimates:

   | check | was | now |
   |---|---|---|
   | test top-1 | ≥ 75 % | ≥ 60 % |
   | test top-3 | ≥ 90 % | ≥ 80 % |
   | field top-3 | ≥ 70 % | ≥ 65 % |
   | lowest class recall | ≥ 50 % | ≥ 40 % |

4. Training config `ml/configs/train_v3.json` = train_v2 settings on class list v2.

## Consequences
- The app recognizes 13 rocks in v1. Any other rock gets the closest of the 13, so the "uncertain" result
  (fitted in 03_evaluate) and the top-3 display matter more; the UI should say which rocks it knows.
- The 16 dropped classes (amphibolite, andesite, chert, conglomerate, evaporite, hornfels, marble, mudstone,
  phyllite, pyroxenite, quartzite, rhyolite, schist, scoria, slate, talc-carbonate) return as photos are collected
  (Wikimedia Commons, own photos). A label change is a MAJOR model version (architecture §3.5).
- A family-level fallback ("probably a metamorphic rock") is worth testing: the 29-class model already got the
  family right 65 % of the time.
- Encyclopedia (Phase 8) can still cover all rocks; only identification is limited to 13.
