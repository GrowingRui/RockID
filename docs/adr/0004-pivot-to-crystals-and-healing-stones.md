# ADR 0004 — Pivot: identify crystals and healing stones

Date: 2026-11-01 · Status: **accepted** (owner decision)

## Context
Phases 1–2 built and validated an identification pipeline for geology rock types (Kaggle
`kutlayusta/type-of-rocks-and-minerals-dataset`; best model 13 classes, val top-1 65 %, ADR 0003).
The owner clarified the product: an app that identifies **crystals and healing stones** (amethyst,
rose quartz, tiger's eye…) and tells the user what the stone is, its description, and its traditional
meaning and uses (energy, luck, healing traditions).

## Decisions
1. **Replace** the geology scope. The rock-type work stays in git history and `ml/reports/`, but is no
   longer the product. ADRs 0001 and 0003 (rock class lists, rock gate) are superseded for the product.
2. **Keep the pipeline**: audit, dedup, leak-free splits, training, TF.js smoke test, evaluation and
   gate, export, the web app, accounts and collection (ARCHITECTURE.md §1–6) apply unchanged.
3. **~20 most popular stones** in the first model; more are added as photos are collected.
4. **Photos users will take**: tumbled/polished stones and jewelry/cut gems. Training data must
   match these forms (a raw-crystal dataset would not).
5. **Meanings are presented as tradition**, never as fact: "In crystal healing traditions, rose quartz is
   associated with love…", with a short "not medical advice" note on every stone page and result. No
   claims that a stone treats, cures or prevents illness. Physical facts (what the stone is, hardness,
   origin, care) are stated plainly, with sources.
6. Results say "looks like …". The app never claims a stone is genuine: dyed, heated and imitation
   stones (dyed howlite as turquoise, heated amethyst as citrine, glass) often look identical in a photo.

## Consequences
- **Data is the main work.** No public dataset of tumbled stones exists. The Kaggle gemstone set
  (`lsind18/gemstones-images`, ~3,200 images, 87 classes) is mostly cut gems with ~37 images per class.
  Candidate sources: Roboflow "Crystals" (85 classes, license and content to check), Wikimedia Commons,
  the owner's own photos, and web images used for training only (same policy as before).
- Cut-gem identification is less reliable than tumbled stones (same color, different material);
  the uncertain result and top-3 display matter most there.
- Class list, gate and encyclopedia content are redone for stones (new ADR once the data audit is in).
- Product naming ("RockID") may change; not decided here.
