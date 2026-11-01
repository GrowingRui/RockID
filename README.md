# RockID

Identify crystals and healing stones from a photo, entirely in the browser, then learn what they are,
their traditional meanings, and keep a personal collection
([ADR 0004](docs/adr/0004-pivot-to-crystals-and-healing-stones.md); the earlier rock-type work is in `ml/reports/`).

- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Phases and acceptance criteria: [docs/PHASES.md](docs/PHASES.md)
- Setup checklist and open questions: [docs/phase-0-setup.md](docs/phase-0-setup.md)
- ML pipeline (Google Colab): [ml/README.md](ml/README.md)

> AI identification can be wrong, and a photo cannot tell a genuine stone from a dyed or imitation one.
> Meanings are traditional beliefs, not medical advice.

## Layout

| Path | Contents | Phase |
|---|---|---|
| `ml/` | Python dataset audit, training and export (Colab) | 1–3 |
| `apps/web/` | React + TypeScript + Vite web app | 4+ |
| `packages/types`, `packages/core` | Shared types and business logic | 4+ |
| `supabase/` | Migrations, RLS policies, seed data | 5 |
| `content/encyclopedia/` | Encyclopedia entries with sources and licenses | 8 |
| `docs/` | Architecture, phases, decisions | — |
