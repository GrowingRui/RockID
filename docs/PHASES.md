# RockID — Phases

Phases 1–3 (ML, Google Colab) and Phase 4 (web foundation) can run in parallel.

| # | Phase | Depends on | Status |
|---|---|---|---|
| 0 | Project setup and decisions | — | in progress |
| 1 | Dataset audit (`ml/notebooks/01_audit.ipynb`) | 0 | done (class list v1 approved) |
| 2 | Model training and evaluation (`02_train`, `03_evaluate`) | 1 | in progress |
| 3 | Model export and release (`04_export`) | 2 (gate passed) | not started |
| 4 | Web foundation and UI/UX (mock model) | 0 | not started |
| 5 | Supabase backend and authentication | 4 | not started |
| 6 | In-browser AI integration | 3, 4 | not started |
| 7 | Collection and identification history | 5, 6 | not started |
| 8 | Encyclopedia | 1 (class list fixed) | not started |
| 9 | Testing, optimization, launch (optional PWA) | 6, 7, 8 | not started |
| 10 | Future: React Native + Expo | web stable for 4 weeks | planning only |

## Acceptance criteria

**0 — Setup.** Repo exists with docs and tooling basics; accounts ready (see
[phase-0-setup.md](phase-0-setup.md)); open questions answered or deliberately deferred.

**1 — Audit.** `ml/reports/audit.md` produced; no duplicate cluster spans splits; every kept class
has ≥ 150 clean images or is merged/dropped; split manifest committed; class list approved by the owner.

**2 — Training.** TF.js export smoke test passes before training. Gate: test top-1 ≥ 75 %,
top-3 ≥ 90 %, field-set top-3 ≥ 70 %, no class recall < 50 %. Re-running from the committed config
reproduces top-1 within ±1.5 points.

**3 — Export.** TF.js ≤ 5 MB and within 1 point of SavedModel top-1; TFLite and TF.js outputs match
SavedModel (max abs diff ≤ 0.02 on 50 images); GitHub Release `v1.0.0` with metadata and checksums.

**4 — Web foundation.** CI green; Lighthouse mobile ≥ 90 on `/` and an encyclopedia page; no axe
violations; full keyboard use; reduced motion respected; initial JS ≤ 150 KB gzip.

**5 — Backend.** pgTAP RLS suite green; type-drift check in CI; no service key in the bundle;
email and Google sign-in work end-to-end.

**6 — Inference.** Browser parity: top-1 matches Python on ≥ 98 % of 50 golden images; first
identification ≤ 5 s incl. download, later ≤ 1 s (p75, reference phone); main thread never blocked
> 200 ms; works on Chrome Android, Safari iOS, desktop Chrome and Firefox.

**7 — Collection/history.** E2E identify → save → edit → delete passes (photo removed from storage);
uploads ≤ 500 KB with no EXIF.

**8 — Encyclopedia.** Every class has a page with source and license shown.

**9 — Launch.** Lighthouse mobile ≥ 85 on all public routes; E2E green on Chromium, WebKit, Firefox;
projected usage within free tiers at 1k monthly users; if PWA: identification works offline.
