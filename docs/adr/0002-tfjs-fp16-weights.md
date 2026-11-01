# ADR 0002 — TF.js weights in float16, not uint8

Date: 2026-11-01 · Status: **proposed** (from the Phase 2 smoke test; owner to confirm)

## Context
Architecture §3.5 planned uint8 weight quantization for the TF.js model (≈3.5–4 MB) because
"fp16 MobileNetV2 is ≈7 MB". The Phase 2 smoke test (`ml/rockid_ml/tfjs_smoke.py`) measured the
actual model: MobileNetV2 α 1.0, 224 px, our 29-class head, TF 2.21 / Keras 3.15 / tensorflowjs 4.22,
run in Node with `@tensorflow/tfjs` 4.22 and compared with Keras on 4 random inputs.

| weights | size | max abs Δ logit | max abs Δ probability | top-1 agrees |
|---|---|---|---|---|
| float32 | 8.72 MB | 0.00001 | 0.000001 | 4/4 |
| float16 | 4.44 MB | 0.023 | 0.0019 | 4/4 |
| uint8 | 2.30 MB | 1.30 | 0.088 | 3/4 |

The ≈7 MB estimate included the 1000-class ImageNet classifier (1.28 M parameters) that we don't ship.
uint8 (per-tensor) is known to hurt MobileNetV2's depthwise convolutions, and here it misses the
Phase 3 parity limit (≤ 0.02) by a factor of four.

## Decision
TF.js weights are **float16** (`tfjs_quantization` in `ml/configs/train_v1.json`). The smoke test now
fails when the size exceeds 5 MB or the probability difference exceeds 0.02.

## Consequences
- Web model ≈ 4.4 MB: inside the 5 MB budget with ~0.5 MB headroom. Adding classes costs ~2.5 KB each.
- Slightly longer first download than uint8 (≈ +2 MB); still within the 5 s first-identification target on the reference network (Phase 6 measures it).
- If a future backbone doesn't fit in fp16, the fallbacks stay as in §3.5 (α 0.75, MobileNetV3), not uint8.
- Numbers are from an untrained head; Phase 3 re-checks parity on 50 real images with the trained model.
