# Funder Match: saved runs, started by the people responsible for an organisation

*Approved 2026-10-10. Builds on `2026-10-10-funder-matching-match-v1.md` (#100). It changes the Funder Match
spec (`features-plans/funder-match/` on `docs/funder-match-spec`) in one place: who may write. The spec has
only `make match` writing, as the owner. Here staff, an organisation's stewards and its admins run and save
a match from the app.*

## Context

The spec stores every run in two private tables, `funder_matches` and `funder_match_details`. Only a
`make match` job, run from a terminal against the database, writes them. So an organisation's admin waits on
staff for every rerun, and the spec's Rerun button waits for v2.

**Decisions:**
- **Who runs and saves:** staff, a steward of that organisation, or an admin of it.
- **Who reads saved runs:** members read them, as the spec says. In chat, only those who may run a match get
  the live answer.
- **Where saving happens:** from the Funder Match page only. A chat save tool can come later if it is wanted.

| Role (`org_members.role`) | Read saved runs | Run + save | Live `compare_fit` in chat |
|---|---|---|---|
| Staff | every org | every org | every org |
| Steward of the org | ✓ | ✓ | ✓ |
| Admin of the org | ✓ | ✓ | ✓ |
| Member of the org | ✓ | — | — |
| Anyone else | 404 | 403 | refused |

## Architecture

```
 entry points, one function
   POST /api/funder-matches/runs?org=kabil   (page button; caller)      make match [ORG=]   (staff backfill; owner)
                    └──────────────┬──────────────────────────────────────────────┘
                                   ▼
   app/matching/service.py   run_and_save(org_id, writer, run_by)
     read   owner pool, read-only:  load(org_id, every funder)       same inputs whoever runs it
     judge  match() × every funder   (pure: app/matching/{rules,rubric,match}.py)
     write  writer pool: the caller (route) or the owner (make match)
            BEGIN; pg_advisory_xact_lock(org)  one run per org at a time
              INSERT funder_matches × N (one run_id, run_at, run_by, rubric_version, score, card)
              INSERT funder_match_details × N
            COMMIT                             all or nothing
   → {run_id, run_at, funders_checked, counts}

 0042_funder_matches.sql
   app.my_match_org_ids() = orgs where the caller is admin or steward
   SELECT  org_id IN app.my_org_ids()       OR app.is_staff()
   INSERT  (org_id IN app.my_match_org_ids() OR app.is_staff()) AND run_by = app.user_id()
   no UPDATE or DELETE grant: a run is never edited
   KNOWN_EXCLUDED, not in Ask's catalog
```

**Why it is shaped this way:**
- **Two locks.**
  - The route checks the role with the same SQL function the policy uses.
  - The insert runs as the caller, so row-level security refuses a wrong-org write even if the route has a bug.

  Example: a SeSTA admin posting `?org=kabil` gets 403. A forced insert is refused by the policy.
- **Same inputs whoever runs it.** The read uses the owner pool, as `compare_fit` and the spec's job do, so a
  steward's run and a staff run on the same data score the same. As the caller, a steward would not see a
  private funder document, and some `org_identifiers` columns are granted by column.
- **Always complete.** A run covers every funder, so "43 funders checked" stays true. A chat comparing two
  named funders is never saved as a run.
- **No model and no cost.** `match()` is pure, so a run takes milliseconds.
- **Audited.** `run_by` records who ran it (NULL for `make match`). The spec had it in v2.

## Changes

| Piece | Change |
|---|---|
| `app/agent/{rubric,rules,match,assessment}.py` | Move to `app/matching/`, where the spec places them. Callers change only their imports |
| `db/migrations/0042_funder_matches.sql` | The spec's two tables and index, plus `run_by uuid REFERENCES users(id)`, `app.my_match_org_ids()`, the grants (authenticated: SELECT and INSERT) and the policies above |
| `app/agent/tools/sql/catalog.py` | Both tables in `KNOWN_EXCLUDED` |
| `app/matching/service.py` | `rows(matches)` (pure: the spec's `card` and `detail`, with `criteria: []` for a NULL score) and `run_and_save(...)` |
| `app/matching/run.py`, `Makefile` | `make match [ORG=slug]`: every org, or one, written as the owner |
| `app/api/routes/funder_matches.py` + `repositories/` + `schemas/` | `POST /api/funder-matches/runs?org=`: 401 signed out, 404 for an unknown org, 403 for a role that may not run, 201 with the run summary. One line in `api/router.py` |
| `app/agent/tools/matching_tools.py` | `compare_fit` refuses unless the chat user is staff, or an admin or steward of the org. An unset chat user is refused |
| `instructions.md`, `funder-matching` skill | Say who may run a match, and that a refusal is reported, never worked around |
| `CLAUDE.md` | `make match`, the migration count, and `app/matching/` in the layout |

## Tests

- **Unit:**
  - `rows()` shapes: `score` equals `detail.score.of_100`, and a NULL score has a one-line card and `criteria: []`;
  - the route through `client_for` with the service patched: 401, 404, 403, 201;
  - the `compare_fit` refusal.
- **Integration** (`integration` mark, rolled back):
  - insert by role: staff, admin_a and steward_a succeed; member_a, member_b and nobody are refused;
  - read by role;
  - a run, then a rerun, keeps both `run_id`s.

## Exit gate

- `pytest -m "not integration"` and the new integration tests pass, and ruff is clean.
- `make migrate && make match` locally writes one row per org × funder.
- `curl` the POST as staff (201) and as a stranger (403).
- A deliberate `make migrate ENV=staging` comes after a backup, with a go-ahead.

## Next

The read API (`GET /api/funder-matches?org=`, `/{id}/detail`), then the page, where the Run match button
shows by role, then the design sync, then retiring the old fit scores.
