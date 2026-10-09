# Model tiers: a strong model to reason, cheaper models for subtasks

## Context
Every agent ran on one model: `MODEL`, which defaulted to `claude-sonnet-5`. `UTILITY_MODEL` was empty, so it fell back to `MODEL`, and the SQL audit was off. Here each model is matched to how hard its work is. The newest strong model reasons, and cheaper models do the subtasks.

The next PR, `2026-10-09-import-middleware.md`, builds on this one with fallbacks, budgets, a rubric for the researcher and an escalation when a save fails.

## Architecture

```
                      browser ── Next.js ── /api/copilotkit (AG-UI)
                                     │
               ┌─────────────────────┴──────────────────────┐
               ▼ /agent                                      ▼ /ingest (staff)
 ┌──────────────────────────────┐        ┌────────────────────────────────────────────┐
 │ ASK SANGAM          [STRONG] │        │ IMPORT SUPERVISOR                 [STRONG] │
 │ Opus 5.5  ·  MODEL           │        │ Opus 5.5  ·  MODEL                         │
 │ plans SQL, cross-checks,     │        │ plans waves, handles pauses, final report  │
 │ writes the cited answer      │        └───┬───────────────┬────────────────┬───────┘
 └──────────────┬───────────────┘            │ task ×N (≤8)  │ task ×N        │ task
                │ after each SQL answer      ▼               ▼                ▼
                ▼                   ┌────────────────┐ ┌──────────────┐ ┌──────────────┐
 ┌──────────────────────────────┐   │ entity-        │ │ catalog-     │ │ workbook-    │
 │ SQL AUDIT            [CHEAP] │   │ researcher     │ │ writer       │ │ reader       │
 │ Haiku 4.5 · SQL_AUDIT_MODEL  │   │ [RESEARCH]     │ │ [CHEAP]      │ │ [CHEAP]      │
 └──────────────────────────────┘   │ Sonnet 5.5     │ │ Haiku 4.5    │ │ Haiku 4.5    │
                                    │ RESEARCH_MODEL │ │ UTILITY_MODEL│ │ UTILITY_MODEL│
                                    └────────────────┘ └──────────────┘ └──────────────┘
        run_import_now (adapter path): article → record  [CHEAP] Haiku 4.5 · UTILITY_MODEL
```

## Tiers

| Tier | Setting | Default | Runs | Why |
|---|---|---|---|---|
| Strong | `MODEL` | `anthropic:claude-opus-5-5` | Ask's main agent; the Import supervisor | Open-ended planning, where one wrong join or merge is the costliest mistake. Runs once per turn |
| Research | `RESEARCH_MODEL` (new) | `anthropic:claude-sonnet-5-5` | `entity-researcher` | Long pages, up to 8 at once, so most of an import's tokens. Judging evidence still needs a capable model |
| Utility | `UTILITY_MODEL` | `anthropic:claude-haiku-4-5` | `catalog-writer`, `workbook-reader` (new here), `run_import_now` extraction | Fixed output shapes, one or two tools, no judgement about sources |
| Audit | `SQL_AUDIT_MODEL` | `anthropic:claude-haiku-4-5` (now on) | Ask's post-answer SQL audit | A cheap second look. It never blocks |

- Blank or unset always means the default in `config.py`, the only place defaults are written. `docker-compose.yml` passes the variables through.
- To run a tier on the main model, set it to the same spec as `MODEL`. `SQL_AUDIT_MODEL=off` turns the audit off.

## Deploying
The deployed backend reads its Vercel env, and that beats the code defaults. Before running Deploy, set (or clear) `MODEL`, `RESEARCH_MODEL`, `UTILITY_MODEL` and `SQL_AUDIT_MODEL` on `sangam-backend`.

## Not in this change
- Extended thinking budgets.
- A separate Ask model: Ask and the Import supervisor share `MODEL`.
