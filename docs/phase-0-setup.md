# Phase 0 — Setup checklist

Only the **Phase 1** items are needed now. The rest can wait until the phase that uses them.

## Needed for Phase 1 (dataset audit)

- [ ] **Google account with Drive space** (~2–3 GB free for the dataset and caches).
- [ ] **Kaggle API token.** kaggle.com → Settings → API → *Create New Token*. This downloads
      `kaggle.json` containing `username` and `key`.
- [ ] **Add the token to Colab Secrets** (key icon in the Colab left sidebar), so it never sits in a notebook:
  - `KAGGLE_USERNAME` = the `username` value
  - `KAGGLE_KEY` = the `key` value
  - Enable "Notebook access" for both.
- [ ] **Put the ML code where Colab can reach it** — choose one:
  - A. Push this repo to GitHub and set `REPO_URL` in the notebook (private repos need a token
       in the `GITHUB_TOKEN` Colab secret), **or**
  - B. Upload the `ml/` folder to `MyDrive/RockID/code/ml` and leave `REPO_URL` empty.
- [ ] *(Recommended)* Start a **field test set**: 10–20 real-world photos per class, taken outdoors
      or by hand, not from the Kaggle dataset. Put them in `MyDrive/RockID/field_test/<class name>/`.
      The audit runs without it, but the Phase 2 gate needs it.

## Needed later

| When | Item |
|---|---|
| Phase 3 | GitHub repo (model releases are published as GitHub Releases) |
| Phase 4 | Node 20+ (installed: v24) and pnpm (`npm i -g pnpm` or `corepack enable`); Vercel account linked to GitHub |
| Phase 5 | Supabase project (free tier); Google Cloud OAuth client for Google sign-in; Docker Desktop for local Supabase |

## Open questions

| # | Question | Needed by | Answer |
|---|---|---|---|
| Q1 | May the audit merge or drop weak classes? | end of Phase 1 | proposed in ADR 0001, awaiting approval |
| Q2 | Add a "not a rock/mineral" class (needs extra negative images)? | Phase 2 | |
| — | Minerals in v1? | Phase 1 | **No: rocks only, minerals later (ADR 0001)** |
| Q3 | 5 s target: measured from tap or page load? Reference device and network? | Phase 6 | proposed: Pixel 6a-class, ~9 Mbps 4G, from "Identify" tap |
| Q4 | Keep guest history locally and import on sign-up? | Phase 7 | |
| Q5 | Store photos for history, or only for saved specimens? | Phase 5 | proposed: specimens only |
| Q6 | Location exact or rounded (~1 km)? Map view? | Phase 7 | |
| Q7 | Users can flag wrong results / contribute photos for retraining? | Phase 5 | |
| Q8 | PWA in MVP or later? | Phase 9 | |
| Q9 | Users under 13/16? Target regions (GDPR)? | Phase 5 | |
| Q10 | GitHub repo name, domain | Phase 3 | |
| Q11 | Analytics: none / Vercel Analytics / other? | Phase 9 | |
| Q12 | Visual direction / brand preferences | Phase 4 | |
