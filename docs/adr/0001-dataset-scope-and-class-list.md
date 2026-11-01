# ADR 0001 — Dataset scope and class list v1

Date: 2026-11-01 · Status: **accepted** (owner approved the class list on 2026-11-01, after audit `ml/reports/audit-20261101-1006`)

## Context
Two audit runs of `kutlayusta/type-of-rocks-and-minerals-dataset`
(`ml/reports/audit-20261031-2119`, `ml/reports/audit-20261101-0939`):

- Folders hold only igneous / metamorphic / sedimentary. With those 3 labels the linear probe reached
  57.5 % (chance 33 %) and a coarse family alone is not a useful answer for hikers.
- File names carry the rock type: 51 types, 10,830 images, **no minerals**.
- With 51 types: linear probe top-1 31.5 %, top-3 50.7 % (chance 2 %). 16 types are below 150 clean images.
- About half of the near-duplicate clusters (360 of 762 in run 1) carry different rock names, so web-scraped label noise is real.
  These clusters are excluded from the splits.
- License field on Kaggle: not stated. Images are used for training/evaluation only, never redistributed.
- Few plain backgrounds (< 5 % in most classes): images are frame-filling close-ups. The background-only
  probe therefore mostly sees rock texture and overstates shortcut risk.

## Decisions
1. **Rocks only for v1.** Minerals are added later from a separate dataset (owner chose option a).
2. **Labels from file names**; the folder is kept as `family` for display ("Basalt · igneous rock").
3. **Class list v1** (`ml/configs/classes_v1.json`), 29 classes:
   - Merge geologically related, visually confusable types: granitoids → granite, migmatite → gneiss,
     green/blueschist → schist, anthracite → coal, flint → chert, siltstone/shale/oil shale → mudstone,
     wackestone/oolite/chalk → limestone, greywacke → sandstone.
   - Drop obscure or non-hand-sample types with little data or near-zero probe recall: granulite, carbonatite,
     komatiite, porphyry (a texture, not a rock), quartzolite, tephrite, turbidite (a deposit), diamictite, tuff.
   - Minimum 100 clean images per class; **obsidian** kept as an exception (55 images, but very distinctive and popular).
4. Tuff, chalk and other dropped/merged types can return when more data is added.

## Consequences
- The Phase 2 gate (top-1 ≥ 75 %, top-3 ≥ 90 %) is ambitious for this noisy data. It stays as the target;
  if training lands short, options are more data (Wikimedia Commons, own photos), fewer classes, or a lower
  gate paired with a stronger "uncertain" result in the UI. Decided after Phase 2, not now.
- The field test set becomes the main evidence of real-world accuracy.
