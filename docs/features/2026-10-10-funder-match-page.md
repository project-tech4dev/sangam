# Funder Match page: the design's screen, with a Rerun match button that saves a run

*Approved 2026-10-10. Stacked on #142.*


## Context
#142 (`feat/funder-match-runs`) saves runs, but only through `POST /api/funder-matches/runs` or `make match`. No screen reads them. The Ask workspace already lists **Funder Match** as a "Soon" placeholder (`features/ask/views/FunderMatchView.tsx`).

The design artifact (Funder Match Prototype v21) defines the screen:
- a header with "Latest run 6 Oct 2026 · 43 funders checked · 3 earlier runs" and **Rerun match**;
- an organisation picker, which depends on the role;
- Strong and Medium summary cards that filter the list;
- filter pills;
- ranked cards: rank, funder, score bar, tier, a score change, 2–4 ✓/! reasons, and "Why this score" loaded on open;
- weak and not-scored funders folded at the foot.

In the design the rerun is "v2" and queued. Here it is real and synchronous: a run is pure code that takes milliseconds.

**Decided:**
- **Rerun button:** shown to staff and to the org's stewards and admins, the same rule #142's API and RLS enforce. The page asks the server and never decides the role itself.
- **Score change:** read from the run before the latest, using rows already saved. No new storage.
- **Out of scope:** proposals (Start/Continue proposal, the Proposals stat). The design's proposal parts wait for the proposals feature.



## Architecture
```
 Ask workspace (client) ── rail: Funder Match (no longer "Soon")
   FunderMatchView
     GET /api/me                → picker: staff = payload.orgs (all); others = memberships; one org = fixed label
     GET /api/funder-matches?org=kabil              (caller pool, RLS)
        → {org, may_run, run|null, counts, matches[score, prev_score, tier, card]}
     [Rerun match]  shown when may_run
        POST /api/funder-matches/runs?org=kabil     (#142: role check + RLS insert, run_by = caller)
        → 201 → status "Saved · run of 10 Oct · 4 funders checked" → GET the list again
     "Why this score" opened → GET /api/funder-matches/{id}/detail   (loaded only when opened)
```
- **Reads run as the caller,** so RLS decides who sees runs:
  - The route first checks `org.id IN app.my_org_ids() OR app.is_staff()` and answers 404 otherwise. Example: a KABIL member asking for `?org=sesta` gets 404, never an empty "not run yet".
- **`may_run` comes from the server,** from the same `find_org` SQL #142 uses (`app.my_match_org_ids()`), so the button and the POST cannot disagree.
- **The page just reads after a save:** it never assembles a run. It re-reads after the POST.

## Milestones

### M1: read API (PR, stacked on #142, branch `feat/funder-match-page`)
| File | Change |
|---|---|
| `backend/app/repositories/funder_matches.py` | Extend `find_org` with `may_read`. Add `latest_run(pool, org_id)`: the latest `run_id`/`run_at`/`rubric_version`, `funders_checked`, `earlier_runs`. Add `list_matches(pool, org_id, run_id, prev_run_id)`: joined to `funders` (slug, name, funder_type), `prev_score` by funder from the previous run, ordered by `score DESC NULLS LAST, funder name`. Add `get_detail(pool, match_id)` with `run_at` and `rubric_version` |
| `backend/app/schemas/funder_matches.py` | `MatchListOut {org, may_run, run, counts, matches}` and `MatchOut {id, funder, score, prev_score, tier, card}`. `tier` is computed with `app.matching.rubric.tier`. Plus `MatchDetailOut` |
| `backend/app/api/routes/funder_matches.py` | `GET ""` (`require_principal`; 404 when the org is unseen or not readable). `GET /{id}/detail` (404 when RLS hides it) |
| `backend/tests/test_funder_match_runs.py` | The spec's API tests via `client_for`: an empty run (`run: null`), NULL scores last, 404 for an org the caller can't see, `may_run` passed through |

**Exit gate:** unit tests and ruff pass. On a throwaway copy of the DB (the recipe in `.memory/STATE.md`), `make match ORG=kabil` twice, then `GET` shows `earlier_runs: 1` and `prev_score` filled.

### M2: the page (same PR)
| File | Change |
|---|---|
| `frontend/features/ask/views/FunderMatchView.tsx` | Rewrite: header and run line, picker, stats, pills, ranked list, folded weak list, empty states (no org; never run, with "Run the first match" when `may_run`) |
| `frontend/features/ask/views/funder-match/{api.ts,MatchCard.tsx}` | `api.ts`: `getMatches`, `getDetail`, `runMatch`, using the `authHeaders()` + `NEXT_PUBLIC_API_URL` pattern from `features/ingest/lib/saveActions.ts`, throwing `detail` on refusal. `MatchCard`: the card plus a `<details>` that fetches the detail on first open |
| `frontend/features/ask/AskWorkspace.tsx` | Pass `payload.orgs` to `FunderMatchView`, as `VaultView` gets them |
| `frontend/features/ask/components/Sidebar.tsx` | Drop `soon: true` from Funder Match |
| `frontend/lib/api/types.ts` | `MeOut`, `MatchList`, `MatchRow`, `MatchDetail` (snake_case, `\| null`) |
| `frontend/app/globals.css` | `.fm-*` classes from existing tokens only (run line, card grid, score delta, reason ✓/!). Reuse `.pill`, `.btn-ghost`, `ProgressBar`, `Tag`, `.import-disclosure`, `.card`, `.view`. No inline styles except the bar width |

**Reused:**
- the role helpers in `features/ingest/lib/access.ts` (`accessOf(me)`);
- `ProgressBar`, `Tag` and `StatRail` (`components/ui/primitives.tsx`);
- the score look from `features/registry/ScoreCard.tsx`;
- Lucide `RefreshCw`, `Check` and `CircleAlert` with `.icon` classes.

**Rerun states:**
- **Idle:** "Rerun match", or "Run the first match" when the org has never been run.
- **Running:** the button is disabled and reads "Running…".
- **Done:** a `role="status"` line, "Saved · 4 funders checked · 1 strong, 3 medium", and the list re-reads.
- **Refused:** the 403 text appears in `.import-error`.

**Exit gate:**
- `npm run lint` and `npm run build` pass.
- By hand on the local stack (after `make migrate`, with your go-ahead):
  - as staff: pick KABIL, Rerun, see "1 earlier run" and the score changes, open "Why this score";
  - a member sees the list and no button;
  - check the page at phone width.

### M3: design system sync (same PR, as CLAUDE.md requires for an Ask screen)
- Add the Funder Match view to `ui_kits/sangam-web/AskWorkspace.jsx`.
- Mirror any new `.fm-*` classes in the design system's `tokens/base.css`.
- Name the changed files in the PR, following `docs/DESIGN_SYSTEM.md` "sync by hand".

## Verification
- Backend: `PYTHONPATH=$PWD pytest -m "not integration"`, ruff on the changed files, and the integration tests on the DB copy.
- End to end: `make up` → `/ask` → Funder Match.
  - Rerun as staff (dev user) → `funder_matches` gains a run with `run_by` set (`make psql`).
  - The page shows the new run line and the deltas.
- Then ask before pushing and opening the PR (base `feat/funder-match-runs`).
