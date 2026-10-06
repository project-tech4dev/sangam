# Funder matching in Ask Sangam: a counted shortlist, then an agent assessment

> **Superseded 2026-10-06** by `2026-10-06-funder-matching-engine.md`: matching moves from prompt procedures to a deterministic engine behind tools. The crosswalk (`0022`) described here is kept.

*Draft v1 — 2026-10-06. Restructured in place from the 2026-10-05 spec; see Notes.*

## 1. Goal

**A fundraiser asks Ask Sangam which funders fit their organisation, then asks how well one of
them fits. Neither answer ever presents a funder Sangam knows nothing about as a bad match.**

Two questions, asked in the chat that already exists:

| | the question | cost | what comes back |
|---|---|---|---|
| **Flow 2 — shortlist** | *"Which funders fit KABIL?"* | one `db_query`, no rubric | 42 funders in two blocks — *ranked* and *not enough recorded to rank* — with each criterion marked **match / no overlap / not recorded** |
| **Flow 1 — assessment** | *"How does KABIL score against HDFC Bank?"* | five or six tool calls, reads the rubric | a total out of the points that could be scored, the matched criteria, and every criterion it could not score, with the reason |

Success is not that a number appears. Success is that **unrecorded and absent stay visibly
different answers.** Today four of 42 funders carry a sector tag, and zero organisations carry a
Schedule VII one. A ranking built on that ranks *how well-researched a funder is*. A ranking reads
as authoritative, so hiding that is worse than having no ranking.

Scope: no UI, no REST endpoint, nothing stored, no new tool. The work is one research run, one
migration, two catalog caveats and two prompt sections.

## 2. Blast radius

Built by hand — this repo has no `domain-map.md`. Sources: `catalog.py` (the 41 tables and their
foreign keys), `CLAUDE.md`'s Architecture section, `db/migrations/README.md` and
`docs/DATA_PLATFORM.md:229` (where `0002_taxonomy.sql` added `tags.meta`). Every figure below is
from the **local compose database, measured 2026-10-06**. Staging may differ.

| surface | hop | why affected | status | notes |
|---|---|---|---|---|
| `tags` (40 `sector`, 12 `csr_sector`) | 0 | `0022` writes `meta.maps_to` on every sector tag | in scope | M1 |
| `funder_tags` | 1 | the 0a run adds `csr_sector` rows | in scope | data operation, not a PR |
| `org_tags` | 1 | read only; 10 of 11 orgs tagged, **Goonj has none** | in scope (read) | no writer added |
| `funder_footprints` · `funder_locations` · `org_locations` · `locations` | 1 | the geography criterion | in scope (read) | the spec missed `funder_locations` — see §3 |
| `rubrics` · `rubric_criteria` | 1 | Flow 1 reads the weights | in scope (read) | v2, 7 criteria, 15 sub-criteria, 100 points |
| `funder_eligibility` · `org_identifiers` · `grants` | 1 | Flow 1 supporting evidence | in scope (read) | `funder_eligibility` has 0 rows |
| `funders.grant_size_min/max` | 1 | rubric 6a | **unaffected** | not in the SQL catalog, so the agent cannot see them; 6a is unscorable |
| SQL catalog `defects` on `funder_tags`, `org_tags` | 1 | caveats travel with every row | in scope | M2 — not a new table, so no new reach |
| Ask Sangam prompt `app/agent/instructions.md` | 1 | two procedures, rule 4 and rule 2 | in scope | M2, M3 |
| Ask Sangam tool list `app/agent/build.py` | 1 | stays at six | unaffected | validator accepts both query shapes — checked |
| Sangam Import | 1 | can read `tags.meta` via the catalog | unaffected | nothing it does reads `maps_to` |
| `repositories/funders.py` → `ProfileTabs.tsx:273` | 2 | registry page renders every `funder_tags` label, no kind filter | **accepted as-is** | confirmed in conversation, 2026-10-06: funders gain Schedule VII chips after 0a |
| `/meta/tags` (`schemas/meta.py` `TagOut`) | 2 | serialises tags | unaffected | `TagOut` does not expose `meta` |
| `seed/seed.py:128` | 2 | inserts the sector tags **after** migrations run | in scope | drives the shape of `0022` — see §4 |
| `seed/graph_seed.py` | 2 | reads tag labels | unaffected | only if someone re-runs `make graph-seed` |
| `fit_scores` · `fit_score_items` · `score_adjustments` | 2 | Flow 1 can quote the 8 stored scores | unaffected | nothing written |
| Frontend `features/ask/` | 2 | renders the answer | unaffected | no new tool, so no new label in `toolLabels.ts` |

## 3. High-level design (HLD)

```
┌─ Ask workspace — unchanged ──────────────────────────────────────────┐
│  "Which funders fit KABIL?"      "How does KABIL score against X?"   │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ AG-UI (SSE) · /api/copilotkit → /agent
                                 ▼
┌─ Ask Sangam — six tools, unchanged ──────────────────────────────────┐
│   FLOW 2 — shortlist            │   FLOW 1 — assessment              │
│   one SELECT. Counts each       │   reads rubric_criteria (weights)  │
│   criterion AND its coverage.   │   reads the pair's overlap counts  │
│   No rubric, no judgement.      │   reads evidence rows, cites each  │
│   ~1 tool call                  │   ~5–6 tool calls                  │
└───────────────┬─────────────────────────────────┬────────────────────┘
                │ db_query: catalog allowlist · read-only txn · ≤50 rows
                ▼                                 ▼
   NGO side             funder side               rubric
   org_tags ──┐         funder_tags               rubrics
   org_locations        funder_footprints (gave)  rubric_criteria
   org_identifiers      funder_locations (stated)
              │         funder_eligibility · grants
              │ one hop
   tags.meta->>'maps_to'   ← M1: the crosswalk, the one thing added
   sector tag → Schedule VII slug
```

Touched: **Postgres only.** No Neo4j, no Supabase Storage. The model is touched only through the
prompt.

> **The rule:** SQL counts; the agent judges.
> **Example:** the shortlist ranks HDFC above Oil India because it meets two criteria to one. It
> never ranks it because 15 + 8 > 15. Only Flow 1 reads `rubric_criteria.points`.
> **Why it matters:** the first `CASE WHEN … THEN 15` in a query gives the rubric a second home.

**The key trade-off: no `fit_signals` view.** Every table the shortlist reads is already
catalogued, so a view adds no reach. It adds a second path to the same rows, which is the failure
`CLAUDE.md` records for `search_orgs`. The one guarantee a view would give — a count never arrives
without its denominator — is enforced instead by the prompt, the catalog caveats and the evals.
If evals show the model reporting *no overlap* where the truth is *not recorded*, that is the
evidence for a view, and it gets added then.

### The three criteria, and the denominator each must carry

| criterion | overlap | denominator in the same row |
|---|---|---|
| **geography** | org districts and their parent states, met against funder footprints (where it *gave*) and `funder_locations` (where it *says* it gives) | org location count · funder footprint count · funder stated-location count |
| **taxonomy** | `org_tags` ∩ `funder_tags`, both `kind='sector'` | each side's sector tag count |
| **thematic** | org sector tags expanded through `tags.meta->>'maps_to'`, met against funder `csr_sector` tags | org tags that mapped · funder `csr_sector` count |

> **The rule:** never select a count without the denominator behind it.
> **Example:** Priya asks which funders fit Goonj. Goonj has eight locations and no tags. Every
> funder's taxonomy overlap is 0 — the same 0 an active mismatch gives. With `org_sector_n = 0` in
> the row, the agent says *thematic: not recorded for Goonj*, not *no overlap*.
> **Why it matters:** a wrong zero does more damage in a ranking than anywhere else in the product.

A criterion is **known** when both sides have data and **met** when they overlap. Order by
criteria met, then criteria known, then shared districts. A funder with zero known criteria goes
in a separate, named block — not at the bottom of the list.

### Three geography decisions the spec left open

| decision | resolved as | the alternative and its cost |
|---|---|---|
| Is `funder_locations` evidence? | **Yes, as a separate sub-signal.** Geography is *known* if either table has a row. A match reports which table. | footprints only: the 3 funders with only stated geography read *not recorded*, which is false |
| Pan-India (`kind='country'`, 4 of 27 rows) | **A third state: "stated pan-India".** Counts as known, not as met | counting it as a match puts every pan-India funder above every regional one |
| District vs state | **District match and state match are separate columns**, via `locations.parent_id` (rubric 2b vs 2a) | one `geo_overlap` column hides whether a funder works in the org's district or only in its state |

Footprints carry `fiscal_year`. The row surfaces the latest matched year, so "gave in Kokrajhar in
FY2019-20" never reads as current.

### What the data can and cannot become

| | 4 funders, 14 rows | 12 funders | 0 orgs |
|---|---|---|---|
| `kind='sector'` on funders | **capped** — only `seed/seed.py` writes it | | |
| `kind='csr_sector'` on funders | | grows with 0a | |
| `kind='csr_sector'` on orgs | | | **never** — `promote.py:595` declines on purpose |

After M1, **thematic is the criterion that carries tag matching.** Taxonomy is a bonus signal on
the seeded subset, and that is a permanent cap, not backlog.

## 4. Low-level design (LLD)

### 0a — the research run (a data operation, not a PR)

Sangam Import's funder research over the funders with no `csr_sector` tag (30 locally) — see Open
question 1. Locally first, then `ENV=staging` after a backup — confirmed in conversation,
2026-10-06.

What it can move, stated plainly:

- It writes `csr_sector` only. `writer.py:563` (`write_funder_tag`) resolves every theme through
  `taxonomy.CLAUSES` (`taxonomy.py:21-54`).
- It is **`ON CONFLICT DO NOTHING`**, not an upsert. A re-run adds missing clauses and never
  corrects or removes a wrong one. (The 2026-10-05 spec said otherwise.)
- It never touches `org_tags`. After 0a the two sides are better populated and **still not
  joinable**. That is expected. M1 connects them.

Running 0a before writing M1 means the crosswalk is curated against the clauses funders actually
carry, not against a static file.

### M1 — `db/migrations/0022_taxonomy_crosswalk.sql`

The spec wrote this as 40 `UPDATE tags SET meta = …` statements. **That is a no-op on every fresh
database:** `make up` and `make seed` run `migrate` first (`Makefile:83-89, 110-119`), and only
then does `seed/seed.py:128` insert the sector tags. The 40 UPDATEs would match zero rows, be
recorded as applied, and never run again.

So `0022` inserts the rows it annotates:

```sql
INSERT INTO tags (slug, label, kind, meta) VALUES
  ('education-literacy', 'Education & Literacy', 'sector',
     '{"maps_to": "csr-education-and-livelihoods"}'),
  ('micro-finance-shgs', 'Micro Finance (SHGs)', 'sector',
     '{"maps_to": "csr-hunger-poverty-health"}'),
  ('tribal-affairs',     'Tribal Affairs',       'sector',
     '{"maps_to": null}'),                       -- an explicit "no clause"
  ...
ON CONFLICT (slug) DO UPDATE SET meta = tags.meta || EXCLUDED.meta;
```

*(The mappings above illustrate the shape. The real ones are curated in M1.)*

- **Order-independent.** `seed.py:128`'s own conflict clause updates `label` only, and
  `tags.meta` is `NOT NULL DEFAULT '{}'` (`0002_taxonomy.sql:10`), so either order leaves `meta`
  intact.
- **Every one of the 40 carries the `maps_to` key**, set to a slug or JSON `null`. `->>` returns
  SQL NULL for both a missing key and a JSON null, so the shortlist cannot tell them apart.
  `meta ? 'maps_to'` can: it is the check that every tag was *decided*.
- **Slugs are copied from the live table, never re-derived.** `seed.py:128` computes
  `slugify(label)`. A hand-typed slug one character off (`education-literacy` vs
  `education-and-literacy`) never conflicts, and a fresh database ends up with 80 sector tags —
  40 annotated, 40 bare. Transcribe `slug` and `label` from
  `select slug, label from tags where kind='sector'` on the seeded local database, and escape the
  `'` in `Women's Development` on paste.
- **`maps_to` is a slug of a `csr_sector` tag**, joined by `slug`, not by id. Ids differ between
  local and staging. There is no foreign key, so `0022` running before `taxonomy_seed` creates
  those 12 rows breaks nothing.
- Sources to transcribe from, not files the migration loads: `taxonomy.py:21-54` (`CLAUSES`),
  `frontend/features/taxonomy/data/themes.json`, and 0a's output. `app/db/migrate.py` runs SQL
  and nothing else.
- `parent_id` stays unused, kept for a real hierarchy later.

Only 33 of the 40 sector tags are used by any org. All 40 get mapped anyway: the seven unused ones
will be used the day an org is tagged with them.

### M2 — the catalog caveats and the Flow 2 procedure

**Catalog (`backend/app/agent/tools/sql/catalog.py`)** — `defects` lines only. No table and no
column added, so no new reach.

- `funder_tags` (`:374`): *"Two kinds live here. `sector` rows came from the seed and cover 4
  funders; `csr_sector` rows come from research. A funder with no rows of a kind has not been
  researched for it — never 'has no focus'."*
- `org_tags` (`:635`): *"`kind='sector'` only; nothing writes `csr_sector` for an org. Reach
  Schedule VII through `tags.meta->>'maps_to'`. An org with no rows is untagged, not unfocused."*

These reach both flows, and any free-form tag question, through the mechanism rule 10 already
relies on.

**Prompt (`backend/app/agent/instructions.md`)** — a new section, *"Shortlisting funders for an
organisation"*, after rule 10:

1. Resolve the org by name or slug. Confirm which one if the name is ambiguous.
2. One query for that `org_id`: per funder, each criterion's overlap **and** its denominators,
   plus `criteria_met` and `criteria_known`. Order by met, then known, then shared districts.
3. Report two blocks: **ranked** (`criteria_known >= 1`) and **not enough recorded to rank**
   (`criteria_known = 0`), the second block's funders named.
4. Per funder, per criterion, one of: *match* / *no overlap* / *not recorded* (and for geography,
   *stated pan-India*).
5. Say how many of the 42 could be ranked at all.
6. Offer the assessment as the next step. **Do not run it unasked** — it is five more tool calls.

The query is the model's to write. The prompt gives the column contract, not the SQL.

### M3 — the Flow 1 procedure, and rules 2 and 4

A second section, *"Assessing one organisation against one funder"*:

1. Read the rubric from `rubric_criteria` (v2 unless asked), so rubric v3 needs no deploy.
2. Read the pair's overlap counts and denominators — the Flow 2 columns, for one funder.
3. Score each sub-criterion from the underlying rows, citing each.
4. List every criterion it could **not** score, with the reason. Always among them: **6a, grant
   size** — Sangam holds no grant size for any funder. **4b, hard gates**, reads *no eligibility
   bars recorded*, never *sets no bars*.
5. Total as **N / M available points**, never out of 100.

**Rule 4** today: *"Fit scores are rubric-based assessments by a single human rater."* There are
now two kinds of score. The extension: a **stored** score cites `[score:N]`; a **computed**
assessment carries no marker and says so in words.

**Rule 2** says *"a sentence without a marker must not contain a database fact."* The total has no
marker. The reconciliation, written into the prompt: **each input to the total cites its row; the
total is labelled as computed from them** — *"28 / 70 available points, computed by Ask Sangam
from the rows cited above."*

### What does not change

- `app/agent/build.py` — six tools. `test_prompt.py:50` (`test_prompt_names_every_registered_tool`)
  stays green.
- `validator.py` — both query shapes were run through `validate()` on 2026-10-06: a CTE using
  `meta->>'maps_to'`, and a geography roll-up with `UNION ALL`, `FILTER` and `bool_or`. Both pass.
- Frontend — nothing. The registry chips are accepted as-is.

## 5. Security review

| check | finding |
|---|---|
| New endpoints | **None.** Nothing to put `Depends(get_current_user)` on. |
| Input validation | No new boundary. User text reaches SQL only through `db_query`, whose validator regenerates the AST — the model's string never executes (`docs/SQL_AGENT.md`). |
| New catalog reach | **None.** Every table read is already catalogued. M2 adds `defects` text only. `grant_size_min/max` stay out. |
| Migration | `0022` is additive (`INSERT … ON CONFLICT`). It writes vocabulary, not user data. |
| PII, credentials, tokens | None touched. Tags, locations and rubric weights are public reference data. |
| Secrets | 0a reads `ANTHROPIC_API_KEY` and Tavily's key from the environment, as Import already does. |
| Write path | 0a writes into whichever database `ENV` selects. `ENV=staging` writes into the database the deployed app serves — hence local first, then staging after a backup. |

The standing caveat, unchanged by this work: the app connects as a superuser, and the catalog is
the only thing keeping model SQL away from checkpoint tables (`CLAUDE.md`, SQL tools).

## 6. Testing

**Unit (no database):** none needed. No tool, router or repository changes. The prompt-loading
tests in `tests/test_prompt.py` must stay green.

**Integration (`integration` mark, compose Postgres on :5433), in `tests/test_sql_integration.py`:**

- *already landed (93585c1):* `funders` stays under the row cap. Correction to the spec: truncation
  is **not** silent — `render.py:92` tells the model *"the LIMIT truncated the result"*. The test
  still earns its place: past 50, the shortlist is visibly short, not complete.
- **new, M1:** every `kind='sector'` tag has the `maps_to` key (`meta ? 'maps_to'`).
- **new, M1:** every non-null `maps_to` names an existing `csr_sector` slug — no dangling crosswalk.
  This assumes a **seeded** database; on a half-set-up checkout it fails for that reason, not
  because of migration order.

**File-shape test (no database), M1, in `tests/test_migration_integrity.py`:** `0022` contains
`ON CONFLICT (slug)` and no bare `UPDATE tags`. That pins the exact bug the spec's design had.

**Manual gate, M1:** survival of seed order is checked on a fresh volume (below), not by an
automated test. Emptying the sector tags inside a test would mean deleting `org_tags` and
`funder_tags` rows first.

**Evals (`eval` mark, cost money)**, in `tests/evals/cases/golden.jsonl`. Assertion-only
cases (`must_mention`, `must_not_mention`; no `gold_sql`):

| id | question | must | must not | tags |
|---|---|---|---|---|
| `shortlist-unrankable-named` | Which funders fit KABIL? | name the not-enough-recorded block | present those funders as low fit | `canary` |
| `shortlist-org-untagged` | Which funders fit Goonj? | *not recorded* for thematic | *no overlap* for thematic | `canary` |
| `assess-grant-size-unscorable` | How does KABIL score against HDFC Bank? | 6a / grant size as unscorable | a number for grant size; *out of 100* | — |
| `assess-no-bars-recorded` | Does HDFC Bank set eligibility bars KABIL fails? | *no eligibility bars recorded* | *sets no bars* | `canary` |
| `shortlist-pan-india` | (a funder with only a country-level location) | *pan-India* | that funder as a geography match | — |

**Zero-means-unrecorded — where it bites:**

| zero | means |
|---|---|
| Goonj's 0 `org_tags` | untagged, not unfocused |
| 8 funders with no tag, footprint or stated location | unresearched, not a poor fit |
| `funder_eligibility` 0 rows | nobody read the policy, not "no bars" |
| `grant_size_min/max` all null and uncatalogued | unknown, not "any size" |
| `maps_to: null` | curated as "no Schedule VII clause" — **the one zero that is a real answer** |

## 7. Milestones

| | what ships | PR? | gate |
|---|---|---|---|
| M0 | plan, diagram, row-cap test | done | committed on this branch |
| 0a | research tags for the untagged funders | no — a data run | psql counts |
| M1 | the crosswalk migration | yes | integration tests |
| M2 | catalog caveats + the shortlist procedure | yes | canary evals |
| M3 | the assessment procedure + rules 2 and 4 | yes | evals |

The order has a reason. 0a before M1, so the crosswalk is curated against real tags. M1 before M2,
so the shortlist has a thematic join to describe. M2 before M3, because Flow 1 reuses Flow 2's
columns.

#### Milestone 0: the plan and the diagram — done

- **Deliverable**: this document; the archify diagram (8917b09,
  `.archify/architecture-funder-matching-20261005-235522/`); the row-cap test (93585c1).
- **Touches**: docs, one test.

#### Data run 0a: Schedule VII tags for the untagged funders

- **Deliverable**: every researched funder carries at least one `csr_sector` tag, or a recorded
  reason it got none.
- **Touches**: db (rows only), money (model and Tavily spend).
- **Key tasks**:
  - [ ] locally, run Import's funder research in waves of `MAX_PARALLEL_RESEARCH` (8)
  - [ ] record the clause distribution — it is M1's curation input
  - [ ] back up staging; `make migrate ENV=staging` (owed for #89); repeat the run with `ENV=staging`
- **Acceptance criteria**:
  ```bash
  make psql   # select count(distinct ft.funder_id) from funder_tags ft
              #   join tags t on t.id = ft.tag_id where t.kind = 'csr_sector';   -- was 12
  ```

#### Milestone 1: the sector → Schedule VII crosswalk

- **Deliverable**: every sector tag says which Schedule VII clause it maps to, or says it maps to
  none, on fresh and existing databases alike.
- **Touches**: db, backend tests.
- **Key tasks**:
  - [ ] transcribe the 40 `slug`/`label` pairs from the seeded local `tags` table — never re-slugify
  - [ ] curate 40 mappings from `CLAUSES`, `themes.json` and 0a's distribution
  - [ ] write `0022_taxonomy_crosswalk.sql` as `INSERT … ON CONFLICT (slug) DO UPDATE SET meta`
  - [ ] add the two integration tests and the file-shape test in §6
- **Acceptance criteria**:
  ```bash
  make migrate && make migrate-status          # 0022 applied
  make psql   # select count(*) from tags where kind='sector' and meta ? 'maps_to';   -- 40
  cd backend && pytest tests/test_sql_integration.py && pytest -m "not integration"
  ```
  Then the same on a fresh volume (`make down -v && make up && make seed`) — the case the spec's
  `UPDATE` design would have failed.

#### Milestone 2: the shortlist

- **Deliverable**: *"Which funders fit KABIL?"* returns two blocks in about one tool call, with
  every criterion in one of the three states.
- **Touches**: backend (catalog `defects`), prompt, evals.
- **Key tasks**:
  - [ ] the two `defects` lines in `catalog.py`
  - [ ] the shortlist section in `instructions.md`
  - [ ] eval cases `shortlist-unrankable-named`, `shortlist-org-untagged`, `shortlist-pan-india`
- **Acceptance criteria**:
  ```bash
  cd backend && pytest -m "not integration" && ruff check app/agent
  make up && make logs | grep -i "catalog\|undeclared"   # catalog verifies clean
  make evals TAG=canary                                   # COSTS MONEY
  ```
  By hand: ask about KABIL and about Goonj. Count the tool calls; read the second block.

#### Milestone 3: the assessment

- **Deliverable**: *"How does KABIL score against HDFC Bank?"* returns N / M available points,
  each input cited, every unscorable criterion listed with its reason.
- **Touches**: prompt, evals.
- **Key tasks**:
  - [ ] the assessment section in `instructions.md`
  - [ ] extend rule 4 (stored vs computed scores); reconcile rule 2 (inputs cite, total is labelled)
  - [ ] eval cases `assess-grant-size-unscorable`, `assess-no-bars-recorded`
- **Acceptance criteria**:
  ```bash
  cd backend && pytest tests/test_prompt.py
  make evals                                              # COSTS MONEY
  ```
  By hand: one stored pair (KABIL has 8 `fit_scores`) — the answer must separate the stored
  `[score:N]` from the computed total.

No milestone touches the frontend, so none has an `npm run build` gate.

## 8. Open questions and risks

1. **0a scope — open.** Research the 30 untagged funders, or all 42? Because `write_funder_tag` is
   `DO NOTHING`, re-running the 12 tagged ones can add clauses but cannot fix wrong ones.
   *Recommendation:* the 30 untagged — about four waves instead of six. Left open in conversation,
   2026-10-06.
2. **0a spend is the largest cost here**, and it is paid twice (local, then staging). No figure yet;
   measure the local run before starting staging.
3. **Staging is not verifiable right now.** Both Vercel projects are paused (`DEPLOYMENT_PAUSED`)
   and production has served 503 since 1 October.
4. **Vocabularies will not line up.** Live sector slugs mix Darpan free text (`Women's Development
   & Empowerment`) with lowercase rubric labels (`sustainable livelihoods`). Curation is by hand
   either way; the three sources check each other.
5. **Crosswalk drift.** A sector tag added after `0022` arrives with no `maps_to` key. The M1
   integration test catches it, but only when the integration suite runs.
6. **The prompt is the only guarantee of denominators.** If evals show *no overlap* reported for
   *not recorded*, the `fit_signals` view returns as the fix (§3).
7. **Row cap.** 42 of 50. The test fails the day it reaches 50; paging the shortlist is the answer
   then, not a raised cap.
8. **Pre-existing and not caused by this work:** 3 failures in `tests/test_migration_integrity.py`
   and 72 `ruff check .` errors reproduce identically on `master`.

## Notes

- **This document is the live one.** It was restructured in place on 2026-10-06 into the
  feature-planning format; it is a revision of the 2026-10-05 spec, not a replacement.
- **Superseded, and still on other branches:** `docs/features/2026-10-04-rubric-matching-skill.md`
  on `origin/feat/rubric-matching-skill` proposed a seventh tool (`propose_fit_score`), a
  `POST /scores` endpoint and stored `scored_by = 'model:<name>'` rows. This plan rules out all
  three. Its persistence design is the right starting point if storing assessments is ever wanted.
- **Deleted earlier on this branch:** `2026-10-05-funder-cso-matching.md` and its implementation
  plan, which put Flow 2 behind a REST endpoint. Recoverable from git.
- **Corrections to the 2026-10-05 spec**, all checked against code or the local database:
  - 42 funders, not 45; 12 `csr_sector`-tagged, not 15; 8 with nothing recorded, not 10.
  - `write_funder_tag` is `DO NOTHING`, not an upsert.
  - Truncation at the row cap is flagged, not silent.
  - `grant_size_min/max` are not catalogued, so the agent cannot "see the null".
  - `0022` as `UPDATE`s would not run on a fresh database.
  - Geography omitted `funder_locations`.
  - Goonj, the running example, has no tags. KABIL is now the example for matching, and Goonj the
    example for "not recorded".
- **Out of scope:** any UI (`RfpWatchView.tsx` is the natural home later); storing anything;
  weekly RFP triage (`rfp_matches` keeps its zero rows); populating `grant_size_min/max` — the
  highest-value follow-up, since `funder-intake-research` field 8 already asks for the numbers.
