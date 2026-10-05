# Funder matching in Ask Sangam: a deterministic shortlist, then an agent assessment

## Context

Two flows were asked for, and the ask is explicit that they stay separate:

1. **Score one NGO against one funder.** Pull both sides, score against the predefined
   rubric, and report the score, the matched criteria and the major gaps.
2. **Find the best funders for an NGO.** The user names their org; the system ranks ~50
   funders on three criteria — taxonomy/tags, thematic area, geography — and the user can
   then ask for a deeper assessment of any one of them.

**Everything happens inside Ask Sangam.** No new screen, no new REST endpoint, no frontend
change at all. Both flows are questions asked in the existing chat, which means the whole
feature is a database view, a prompt section, and the crosswalk that makes either worth
running.

That constraint does not dissolve the separation the ask called for — it relocates it:

- **Flow 2 is one cheap SELECT.** All the arithmetic lives in the view; the agent runs a
  single `db_query`, sorts on columns the view already computed, and reports. It reads no
  rubric, fetches nothing per funder, and makes no judgement.
- **Flow 1 is the agent working.** It reads the rubric from the database, gathers evidence
  per criterion with citations, and weighs it.

One shortlist turn ≈ one tool call. One assessment turn ≈ five or six.

### What already exists

Most of the pieces are built. The v2 rubric is **data, not prose** — `rubrics` +
`rubric_criteria`, 7 criteria and 15 sub-criteria, 100 points, each row carrying its `points`
and a plain-English `guiding_question`. Every table this needs is already in the SQL catalog,
so Ask Sangam can read the rubric and write the joins today. `fit_scores` / `fit_score_items`
/ `score_adjustments` model a scored pair end to end, with 8 hand-made rows.

**Nothing is stored by this feature** — carried forward from the earlier decision. An
assessment is an answer, not a row.

### The finding that must shape the design

The three criteria map onto `tags.kind`, which has exactly two inhabited values in live data:
`sector` (40 tags) and `csr_sector` (12, the Schedule VII list). **Two of the three criteria
have almost no data behind them:**

| criterion | maps to | coverage | org–funder pairs with any overlap (of 462) |
|---|---|---|---|
| taxonomy / tags | `tags.kind = 'sector'` | **4 of 42 funders** tagged | **11** |
| thematic area | `tags.kind = 'csr_sector'` | 15 funders tagged, **0 orgs** | **0 — structurally impossible** |
| geography | `org_locations` ∩ `funder_footprints` | 32 of 42 funders, 11 of 11 orgs | 29 |

**The split is structural, not an oversight.** `org_tags` is written only by
`seed/seed.py:155` (`kind='sector'`); the ingest pipeline refuses to write it at all —
`backend/app/ingest/promote.py:595` says *"org_tags is not a concept, and nothing on the org
side resolves a sector anyway."* `funder_tags` is written by the seed (`sector`) **and** by
`backend/app/ingest/writer.py:563` (`write_funder_tag`), which always resolves through
`taxonomy.resolve_csr_sector()` and therefore always writes `csr_sector`. Every tag Sangam
Import will ever add to a funder is on the facet orgs do not use.

`tags.kind` permits nine values and two are ever written, so "taxonomy/tags" and "thematic
area" are not two separable facets in live data either: themes (`Education & Literacy`) and
population groups (`Children`, `Tribal Affairs`, `Differently Abled`) are **all filed under
`kind='sector'`**, with the Schedule VII list as the only other inhabitant.

The join the two sides need exists in the repo but not in Postgres. Two sector→Schedule VII
crosswalks: `backend/app/ingest/taxonomy.py:21-54` (`CLAUSES`, free text → csr slug, consulted
at write time only) and `frontend/features/taxonomy/data/themes.json` (domains → themes →
sub-themes, each carrying `csr: [{clause, sector}]`, `sdgs[]`, `schemes[]`). `tags.parent_id`
and `tags.meta` were added to hold it; nothing populates either. The unbuilt design at
`features-plans/data-model/2026-09-27-data-platform-architecture-design.md:120-127` specifies
exactly this — `org_tag_set` expanded one hop through `meta.maps_to`, Theme signal worth 20.

A shortlist built on these three today would rank funders by **how well-tagged they are**, not
by how well they fit, and would show 10 untagged, un-footprinted funders at the bottom as
though they were poor matches. That is `instructions.md` rule 10's trap — a zero that means
*unrecorded* — in the place it does the most damage, because a ranking reads as authoritative.

So the tag data is fixed before anything is built on it — the research run first, then the
crosswalk — and the view is built so that **unknown and poor are different columns**.

## Architecture

```
┌─ Ask workspace — unchanged ──────────────────────────────────────────┐
│  ChatPane (CopilotKit)   ·   /ask?q= deep links already exist        │
│  "Which funders fit Goonj?"      "How does Goonj score against X?"   │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ AG-UI (SSE) · /api/copilotkit → /agent
                                 ▼
┌─ Ask Sangam — LangGraph deep agent ──────────────────────────────────┐
│  six tools, unchanged.  Two new procedures in agent/instructions.md: │
│                                                                      │
│   FLOW 2 — shortlist            │   FLOW 1 — assessment              │
│   1 × db_query, no rubric,      │   read rubric_criteria (weights)   │
│   no judgement. Order by        │   read the pair's fit_signals row  │
│   criteria_met, then            │   read evidence rows, cite each    │
│   criteria_known.               │   score · matched criteria · gaps  │
│   ~1 tool call                  │   ~5–6 tool calls                  │
└───────────────┬─────────────────────────────────┬────────────────────┘
                │ db_query — catalog allowlist, read-only txn, ≤50 rows
                ▼                                 ▼
    ┌───────────────────────────────┐   ┌────────────────────────┐
    │ fit_signals — VIEW            │   │ rubrics                │
    │ one row per org × funder      │   │ rubric_criteria        │
    │ counts + the coverage         │   │  (weights — read by    │
    │ behind every count            │   │   the agent, never     │
    │ + criteria_met/known (0–3)    │   │   by the view)         │
    └───────────────┬───────────────┘   └────────────────────────┘
                    │ built from
   ┌────────────────┴──────────────────────────────┐
   │ NGO side              │ funder side           │
   │ orgs                  │ funders               │
   │ org_tags ─┐           │ funder_tags           │
   │ org_locations         │ funder_footprints     │
   │ org_identifiers       │ funder_eligibility    │
   └───────────┼───────────┤ grants                │
               │           └───────────────────────┘
               │ one hop through
        ┌──────┴────────────────────────┐
        │ tags.meta->>'maps_to'         │  ← Deliverable 0: the crosswalk
        │ sector tag → Schedule VII     │     that makes the two facets meet
        └───────────────────────────────┘
```

**Where the line falls.** The view does arithmetic and no judgement; the agent does judgement
and as little arithmetic as possible. Rubric weights live in `rubric_criteria.points` and
nowhere else — the first `CASE WHEN … THEN 7` inside `fit_signals` would give the rubric two
homes. That is why flow 2 ranks by **counting criteria met**, not by scoring them.

## Deliverables

Order matters here, so: **save the plan → 0a research run → 0b crosswalk → view → prompts →
evals.**

### Before anything: save the plan

Commit this plan as a dated doc on the feature branch before any code — the house rule. It
goes to `docs/features/2026-10-05-funder-matching-in-ask-sangam.md`. It is the only design
document for this work: the two earlier ones on this branch were written against a shape that
no longer holds and have been deleted rather than left to contradict it.

### 0. Fix the tag data — first, and the real blocker

**Backfill first, then the crosswalk.** Two steps, in that order.

**0a — pull tags and taxonomy for every funder.** Run Sangam Import's funder research over
all 42, not just the 27 with no `csr_sector` tag: re-running the tagged 15 confirms or
corrects what is there, and `write_funder_tag` is an upsert. At `MAX_PARALLEL_RESEARCH=8`
that is six waves. This is a real model spend and the largest single cost in the plan.

Know what it can and cannot move:

- It writes **`csr_sector` only**. `backend/app/ingest/writer.py:563` resolves every tag
  through `taxonomy.resolve_csr_sector()`, so the output is Schedule VII clauses and nothing
  else. It will not add a single `kind='sector'` tag to any funder.
- It never touches `org_tags` — `backend/app/ingest/promote.py:595` declines on purpose.
- So after 0a the two sides are *better populated and still not joinable*. That is expected,
  not a failed run. 0b is what connects them.

**Doing this first is the better order, and not only because it is the ask.** The crosswalk
is 40 hand-curated rows, and curating them against the clauses the funders have actually been
tagged with beats curating them against a static file and hoping. 0a tells us which of the 12
Schedule VII clauses are live and how the funders distribute across them; 0b is then written
with that distribution in front of us. The cost of the flip is that there is no working
shortlist until 0b lands — acceptable, since the shortlist is not being shipped to anyone
mid-sequence.

**0b — materialise the crosswalk.** `db/migrations/0022_taxonomy_crosswalk.sql`. For each
`kind='sector'` tag, write the Schedule VII clause it maps to into `tags.meta->>'maps_to'`
(the v3 spec's own wording), leaving `parent_id` for a real hierarchy later.

- **It is 40 hand-written `UPDATE tags SET meta = …` statements, transcribed.**
  `app/db/migrate.py` applies `db/migrations/*.sql` and nothing more, so a migration cannot
  read `frontend/features/taxonomy/data/themes.json` at runtime. That file and the `CLAUSES`
  keyword table at `backend/app/ingest/taxonomy.py:21-54` are **sources to transcribe from**,
  not inputs the migration loads.
- Expect the vocabularies not to line up. `themes.json` mirrors the unpromoted
  `features-plans/` seed, while the live 40 `sector` slugs are Darpan free text
  (`Women's Development & Empowerment`, `Micro Finance (SHGs)`) alongside lowercase rubric
  labels (`sustainable livelihoods`). The mapping is curated by hand either way; the two
  files and 0a's output are three cross-checks on each other.
- **Every one of the 40 gets either a clause or an explicit "no clause."** A silent null
  reintroduces unrecorded-looks-like-absent one layer up, which is the bug this whole design
  exists to avoid.

It is a data migration and not a query-time judgement on purpose: a crosswalk the model
re-derives per request is a different answer per request.

**What this does not fix, and must not be described as backlog:** criterion 1 (sector↔sector)
is **capped by design**. No writer anywhere adds `kind='sector'` to `funder_tags` except
`seed/seed.py`, so that overlap is permanently limited to the 14 seed-era rows and no amount
of research changes it. After 0b, **thematic area is the criterion that actually carries
tag-based matching**, and criterion 1 should be read as a bonus signal on the seeded subset.
The 10 funders with neither tags nor footprints stay *unknown* until someone researches them.

### 1. The architecture diagram

An interactive HTML diagram via the archify skill (`architecture` type), written to
`.archify/architecture-funder-matching-<timestamp>/`, showing both flows end to end — the
single-query shortlist path and the multi-call assessment path visually separated, with
`fit_signals` as the shared substrate and the crosswalk feeding it. Produced first, before
any code.

### 2. `fit_signals` — the shared substrate

`db/migrations/0023_fit_signals.sql`, after the crosswalk. A view, so nothing is materialised
and nothing is stored. One row per `orgs × funders`, carrying deterministic counts **and the
denominator behind each one**:

| group | columns |
|---|---|
| geography | `shared_district_count`, `shared_state_count`, `org_location_count`, `funder_footprint_count` |
| taxonomy | `shared_sector_tag_count`, `org_sector_tag_count`, `funder_sector_tag_count` |
| thematic | `shared_csr_sector_tag_count` (org side expanded one hop via `tags.meta->>'maps_to'`), `org_mapped_tag_count`, `funder_csr_tag_count` |
| history | `direct_grant_count`, `funder_partner_count` |
| bars | `funder_disqualifier_count`, `funder_eligibility_count` |
| credentials | `org_has_12a/80g/csr1/fcra`, `org_identifier_count` |
| money | `funder_grant_size_min`, `funder_grant_size_max` — carried **so the agent sees they are null** rather than inferring a mismatch |
| ordering | `criteria_met` (0–3), `criteria_known` (0–3) |

`criteria_met` / `criteria_known` are what make flow 2 a single query. A criterion is *known*
when both sides have data for it and *met* when they overlap; a funder with no footprints and
no tags scores `criteria_known = 0`, which sorts it into an **unknown** bucket rather than the
bottom of the ranking. The two are kept separate columns precisely so the agent cannot
collapse them.

Then its entry in `app/agent/tools/sql/catalog.py` (41 → 42 tables), with
`ForeignKey("org_id", "orgs.id")` and `ForeignKey("funder_id", "funders.id")` so rows come
back citable as `[org:N]` and `[funder:N]` with no other change — the inheritance is pinned by
`test_foreign_keys_inherit_the_kind_they_point_at`. Add a `defects` line recording the tag
coverage above, so every result touching the view carries it.

Verified, not assumed: `undeclared_tables()` is fed `information_schema.tables WHERE
table_type = 'BASE TABLE'` (`core/lifespan.py:146`), so a view is never flagged as
undeclared; `verify_against_db()` reads `information_schema.columns` with no type filter
(`catalog.py:1070`), so the view's columns **are** drift-checked exactly like a table's.

**Row cap.** `validator.DEFAULT_MAX_ROWS = 50` and 42 funders fit — the 51st would silently
truncate a one-org shortlist. An integration test asserts `count(*) FROM funders` stays under
it, so the day it stops being true is a failing test rather than a quietly short list.

### 3. Flow 2 — the shortlist, as a prompt procedure

A new section in `app/agent/instructions.md`. **No new tool** — `TOOLS` in
`app/agent/build.py` stays at six.

The procedure, in the prompt's own voice:

- Resolve the org by name or slug, and **confirm which org** before ranking if ambiguous.
- One query against `fit_signals` for that `org_id`, ordered `criteria_met DESC,
  criteria_known DESC, shared_district_count DESC`.
- Report in two blocks, never one list: **ranked** (`criteria_known >= 1`) and **not enough
  recorded to rank** (`criteria_known = 0`), with the second block's funders named, not
  hidden.
- Per funder, per criterion, say which of three states it is in: *match* / *no overlap* /
  **not recorded**. Never let the third read as the second.
- State the denominator — how many of the funders could be ranked at all.
- Offer the deeper assessment as the next step, and **do not perform it unasked**: it is five
  or six more tool calls.

### 4. Flow 1 — the assessment, as a prompt procedure

Another section in the same file, same six tools. The procedure:

- Read the rubric from `rubric_criteria` rather than carrying it in the prompt, so a rubric
  v3 needs no deploy.
- Read the pair's `fit_signals` row for the cheap signals.
- Score the semantic criteria from the underlying rows, citing each.
- Report every criterion it could **not** score as unscorable **with the reason** — this is
  the "major gaps" half of what was asked for, and it is the half that is usually wrong.
- Total as `N / M available points`, never out of 100.

Criterion 6a (grant size, 5 pts) is unscorable for every funder in the database: `0019` added
`funders.grant_size_min/max` and nothing has ever written them.

Rule 4 of `instructions.md` extends too. It currently reads *"Fit scores are rubric-based
assessments by a single human rater, not ground truth."* There are now two kinds of number
with that name and only one is in the database, so the citation convention separates them: a
stored score cites `[score:N]`; a computed assessment carries no marker and says so.

A test already asserts every registered tool is named in `instructions.md`; neither section
adds a tool, so that stays green. The new assertions are eval cases (below).

### 5. Evals

`backend/tests/evals/cases/golden.jsonl` gains cases in the existing format — `id`,
`question`, `required_citations`, `must_mention`, `must_not_mention`, `tags`. The harness
skips gold-SQL comparison when `gold_sql` is absent, so assertion-only cases work.

- a shortlist question must mention the unrankable funders and must **not** present them as
  low-fit;
- an assessment must mention grant size as unscorable and must not state a number for it;
- an org with no locations must produce *geography not recorded*, never *no overlap*;
- every funder must read *no eligibility bars recorded*, never *sets no bars* —
  `funder_eligibility` shipped empty in #89.

Tag the cheap ones `canary` so `make evals TAG=canary` covers the regression surface.

## Verification

### Before 0a — which database is this writing to?

The research run is the one step here that **writes rows**, and `ENV` decides where they
land. `make up ENV=staging` points the local stack at the managed Supabase database the
deployed app serves; the default `ENV=local` writes to the compose Postgres and those tags
exist only on this machine. Two further consequences from CLAUDE.md worth settling before
the run, not after:

- `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` are **not** environment-scoped, so on `ENV=local`
  the `documents` rows are local while the archived files go to the cloud bucket.
- `make migrate ENV=staging` is already owed for #89's `funder_eligibility` —
  `_verify_sql_catalog` raises at boot against an unmigrated database, so staging needs that
  migration (after a backup) before anything else runs there.

### After each step

```bash
# after 0a — did the research actually land?
make psql
#   select count(distinct funder_id) from funder_tags ft
#     join tags t on t.id = ft.tag_id where t.kind = 'csr_sector';   -- was 15, expect ~42
#   select t.label, count(*) from funder_tags ft join tags t on t.id = ft.tag_id
#     where t.kind='csr_sector' group by 1 order by 2 desc;          -- the live distribution
#                                                                       0b is curated against

make migrate && make migrate-status            # 0022 and 0023 listed
make psql                                      # spot-check 0b:
#   select count(*) from tags where kind='sector' and meta ? 'maps_to';   -- expect 40
#   select label, meta->>'maps_to' from tags where kind='sector' order by 2;  -- read it

cd backend
pytest -m "not integration"
pytest tests/test_sql_integration.py           # needs the compose Postgres on :5433
ruff check .

make up && make logs | grep -i "catalog\|undeclared"   # boot must not raise on 0023

make evals TAG=canary                          # COSTS MONEY — the real agent
```

Then by hand in the Ask chat, because no test catches tone:

- *"Which funders fit Goonj?"* — one tool call, two blocks, the unrankable funders **named**;
- *"How does Goonj score against <funder>?"* — a total out of available points, with the
  unscorable criteria listed and grant size among them;
- an org with no `org_locations` row — reads **"geography not recorded"**, never "no overlap".

No frontend change, so no `npm run build` gate for this work.

## Out of scope

- **Any UI.** No new Ask view, no REST endpoint, no component. `RfpWatchView.tsx` stays the
  stub it is. (Noted for later: it is a 20-line placeholder already wired into the sidebar and
  already claiming this concept, so it is the natural home the day a screen is wanted — and
  `MediaView`'s `onDiscuss` → `newChat(seed)` is the ready-made "assess this one" handoff.)
- **Storing anything** — no `fit_scores`, `fit_score_items`, `score_adjustments` or
  `rfp_matches` write. If persistence is wanted later, Sangam Import's `save_research` →
  `promote_research` → hand-written writers is the shape, and that is a third agent.
- Weekly RFP triage. `rfp_matches` keeps its zero rows.
- Populating `grant_size_min/max`. Highest-value follow-up — `funder-intake-research` field 8
  already asks for hard numbers and `0019` built the columns; only the finding→record→writer
  path between them is missing.

## Notes

- Two earlier documents on this branch — `2026-10-05-funder-cso-matching.md` and its
  implementation plan — were deleted when this one landed. They described flow 2 as a REST
  endpoint, pinned a 21-column `fit_signals` contract without the crosswalk-expanded thematic
  columns or `criteria_met`/`criteria_known`, and assumed tag overlap was computable today.
  Their task-level TDD breakdown was written against that shape, so none of it survives the
  change; a fresh one belongs with the view, not before it. Recoverable from git if wanted.
- Pre-existing and not caused by this work: 3 failures in `tests/test_migration_integrity.py`
  and 72 `ruff check .` errors reproduce identically on `master`.
- Both Vercel projects are paused (`DEPLOYMENT_PAUSED`); production has served 503 since
  1 Oct. Nothing here can be verified against the deployed stack until that clears, and
  `make migrate ENV=staging` is owed for #89's `funder_eligibility` before it does.
