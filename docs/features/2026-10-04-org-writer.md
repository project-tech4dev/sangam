# Push org data the way we push funder data

## Context

Sangam Import researches an NGO properly today — it asks the right four concepts, it saves
every finding with the sentence behind it, it publishes a brief, it renders a page. Then it
stops. `promote()` carries an explicit gate (`promote.py:536-542`) that turns NGO research
away, because there is no `OrgRecord`, no `resolve_org` and no `write_org`. Eleven files
across prompts, skills and docs repeat the sentence "orgs has no writer". `grants` has been
waiting on the same thing.

**The database is not the obstacle and never was.** `programs`, `contacts`, `metrics` and
`credential_events` each carry an org-side partial UNIQUE index beside the funder one, plus
`CHECK ((org_id IS NULL) <> (funder_id IS NULL))`. `org_identifiers`, `org_financials` and
`org_locations` mirror `funder_identifiers`, `funder_csr_years` and `funder_locations` column
for column. `documents.org_id` exists. **This PR adds no migration.** It writes the Python half
that was never built.

One row is already waiting. The Goonj run saved 32 findings — 1 identity, 3 identifiers
(FCRA, PAN, CSR-1), 8 locations, 7 documents, 6 contacts, 5 programmes, 2 metrics — all of
which become catalog rows the day this lands.

**Two decisions taken, not to be re-litigated:**

1. **The writer only.** No `credential_events`, no new columns. Both are worth doing and
   neither improves a single already-researched fact, so they go second.
2. **Fill blanks only on an existing org.** The ten hand-vetted cohort rows keep every value
   someone entered by hand; research fills NULLs and reports the rest. This differs
   deliberately from `write_funder`, where a stated value wins — funder rows are all
   machine-made and these are not.

**Branch:** `feat/org-writer`, stacked on `feat/import-skills-spec` (HEAD `8bcefa6`).
Other sessions share this checkout — work in a `git worktree`, and export
`PYTHONPATH="$WT/backend"` there or pytest silently imports the main checkout's `app`.

---

## M0 — the plan on the branch

Commit this document to `docs/features/2026-10-04-org-writer.md`, matching
`docs/features/2026-10-03-import-agent-architecture.md`.

**Exit gate:** branch created off `feat/import-skills-spec`, doc committed, no code touched.

---

## M1 — a name resolves to an org

`app/ingest/matcher.py`, `app/ingest/records.py`.

- **`Match.funder_id` → `Match.entity_id`.** One dataclass serves both kinds; a second would
  duplicate `resolved` and `MERGEABLE`. Call sites are `writer.write_funder`,
  `writer.queue_resolution`,
  `promote._parent`, `promote.promote` and the tests — grep before renaming.
- **`resolve_org(conn, name, identifiers)` — three steps, not four.** Identifier, exact name,
  then boilerplate/trigram against `orgs`. **The alias step does not port**:
  `resolve_funder` queries `funder_identifiers WHERE id_type = 'name'`, and
  `org_identifiers`' CHECK is `pan|12a|80g|fcra|csr1|darpan|cin|reg_no` — no `name`, no
  `domain`. Adding one is a migration; out of scope. `core()`, `core_similarity()` and
  `same_but_for_boilerplate()` are name-only and reused unchanged — note that `NOISE` already
  carries `society`, `sansthan`, `samiti`, `trust`, which is NGO vocabulary.
- **`OrgRecord(Provenance)`** — `name` · `org_kind: Literal["cso","intermediary","government"]`
  (a Literal so a bad value is a held finding, not a mid-transaction DB error) ·
  `legal_form` · `registration_date` · `identifiers: dict[str,str]` with the org CHECK set as
  its allowlist. Reuse `reject_if_aggregate` on `name`: verified against all ten cohort names
  and Goonj, all pass. (Known edge: a bare "Industry" in a name false-positives. Accepted.)
- **`OrgFinancialsRecord`** (four amounts, `is_audited`, `notes`) and **`OrgLocationRecord`**
  (`state`, `district`, `role`, `note`). Note `org_locations.role` has no `priority` value,
  unlike `FunderLocationRecord`, which defaults to it.
- **`funder_name` → `entity_name` on the three shared records only** — `ProgramRecord`,
  `MetricRecord`, `ContactRecord`. Their tables carry both foreign keys; the field is
  validation-only (no writer reads it), so this is a construction-site rename. The seven
  genuinely funder-shaped records keep `funder_name`. Do **not** touch `funder_name` in
  `repositories/` or `schemas/` — that is an unrelated REST field.

**Exit gate:** `pytest -m "not integration"` green; `resolve_org` unit-tested against an
exact hit, a boilerplate hit and a trigram near-miss.

---

## M2 — the writers

`app/ingest/writer.py`, `app/integrations/storage.py`.

`_upsert` (`writer.py:295-331`) is already generic over table and key dict, so the four fact
writers are constants plus thin wrappers, not new SQL.

- **`write_org`** — mirrors `write_funder` with one deliberate difference. A new org inserts
  everything with `registry_status='placeholder'`, which distinguishes an imported row from
  the cohort's `in_vetting`. An **existing** org goes through a fill-blanks variant of
  `_diff`: a column is written only where the stored value is NULL, and every other
  difference becomes a `held` line naming both values. `slugify` and `_free_slug` are reused;
  `_free_slug` gains a table argument, which changes `write_funder`'s call site too.
- **`_write_org_identifiers`** — `ON CONFLICT (id_type, id_value) DO NOTHING`, same shape as
  the funder one. Carry `notes` through. Leave `verified` at its default: research is not
  verification, and the skills' evidenced/claimed distinction has no column here.
- **`write_org_financials`** — mirrors `write_csr_year` on `(org_id, fiscal_year)`, four
  `to_inr` amounts.
- **`write_org_location`** — mirrors `write_funder_location` on `(org_id, location_id)`.
- **Owner-parameterise rather than duplicate**: `write_program`, `write_metric`,
  `write_contact` and `ensure_document` take an owner column plus id instead of
  `funder_id: int`. `ensure_document`'s INSERT hardcodes `funder_id` today (`writer.py:102`)
  and must gain the org path, or no org fact can cite a document.
- **`storage.catalog_key` hardcodes `funders/<slug>/`** (`storage.py:169`). It takes a prefix
  so an NGO's archived PDFs land under `orgs/<slug>/`.

**Exit gate:** each new writer unit-tested with the fake-conn pattern already in
`test_ingest.py`; a second call with identical input returns `matched` and issues no UPDATE;
`_free_slug` against `orgs` returns `goonj-2` when `goonj` already exists.

---

## M3 — promote branches on kind

`app/ingest/promote.py`, `app/ingest/expectations.py`, `backend/tests/test_ingest.py`.

- Delete the org gate (`promote.py:536-542`). `promote()` branches into `_promote_funder` /
  `_promote_org`; `_write_documents`, `_write_programs` and `_write_facts` take an owner.
  **Move the kind branch below the schema-version check.** Today the org gate runs first
  (`:536` before `:546`), so a v1 org row reports "no writer" — a reason that is about to
  stop existing. After this it reports "re-run the research", which is the one that tells
  someone what to do. That change of message is intended.
- **`org_financials` mirrors `csr_year`, not the fact loop.** The funder path handles
  `csr_year` in its own loop in `promote()` before `_write_programs`, keyed on
  `(funder_id, fiscal_year)` and outside `WRITE_ORDER`. Add an `org_financials_from()`
  beside `csr_years_from()` and call it in the same slot.
- **`ORG_WRITE_ORDER`** separate from `WRITE_ORDER`: `org_location`, `metric`, `contact`.
  Appending org concepts to the existing tuple would make the funder path try them.
- **`_row_identity` has no org branches** (`promote.py:326` falls through to `(concept,
  id(f))`, which never collides). Two tuples, each mirroring its table's natural key:
  `org_location → (concept, district_id or state_id)` for PK `(org_id, location_id)`, and
  `org_financials → (concept, fiscal_year)` for UNIQUE `(org_id, fiscal_year)`. Without
  them two findings for one fiscal year silently overwrite each other. `_place` needs no
  change — it reads `state`/`district` by `getattr`, and `OrgLocationFinding` is a
  `PlacedFinding`.
- **`orgs.registered_location_id`**: after locations are written, set it from the
  `org_location` finding whose `role` is `registered`. The registry comment already says a
  registered address is that concept, not a field on `org_identity`. Goonj has exactly one.
- **Report what cannot be stored, do not drop it.** Two known cases, each a `held` line:
  Goonj's `website` (`orgs` has no column and `org_identifiers` has no `domain`), and
  `org_identifier.notes` if the flat identifier map cannot carry it.
- **`entity_research.resolved_org_id` / `resolved_funder_id` are dead columns** — nothing
  writes or reads either, on either path. Set **both** here, one UPDATE after the entity
  write, so the research row links to what it became. Setting only the org one would be
  worse than setting neither.
- **`expectations.py`**: flip the four org concepts to `promotable=True`, delete the
  `_ORGS_HAVE_NO_WRITER` entries and the constant, fix the `concepts_for` docstring, and
  **reword `_GRANT_HAS_NO_WRITER`** — its stated reason is "orgs has no writer", which stops
  being true. The real remaining gate is that a recipient must resolve in `orgs`. Do not
  build a grant writer here.
- **Four tests change, and (a) and (b) must land in the same commit** or they contradict:
  - `test_an_ngo_is_not_written_into_funders` (`:562-576`) — rewrite. It calls
    `promote(None, row)` with `conn=None`, which now `AttributeError`s. The invariant worth
    keeping is that an org never lands in `funders`.
  - `test_what_is_left_out_is_left_out_for_one_reason` (`:791-798`) — the left-out set drops
    to `{"grant"}`.
  - `test_every_finding_field_reaches_a_record` (`:961-974`) — the pivot. It is what forces
    the record classes to carry every org finding field; `RENAMED` needs org rows for
    `id_type`/`id_value`.
  - `test_nothing_is_excused_that_is_actually_written` (`:981-989`) — the reverse gate.

**Exit gate:** `pytest -m "not integration"` green; the Goonj row promotes against the live
container (see Verification) and re-promotes to all `matched`.

---

## M4 — the agent stops saying there is no writer

- **`prompts/catalog_writer.md:6` is a live bug for orgs**: it tells the model to call
  `funder_dossier` with no `entity_kind`, and the parameter defaults to `"funder"`. An org
  write would read the funder tables, see nothing, and report `verified=false` for rows it
  just wrote. It must pass the kind it was given. `_BY_KIND` and `_ORG_DOSSIER_SECTIONS`
  already exist in `catalog_tools.py` and need no change.
- **`PromotionReport`** (`research_records.py:538-561`) — `funder_name`/`funder_id` become
  `entity_name`/`entity_id` plus `entity_kind`. `extra="forbid"`, so this is a model change,
  not an extra key. Update the `still_research` description, which hardcodes a funder example.
- **`instructions.md:160-165` and `:219-234`** — "Do not launch a `catalog-writer` for it"
  inverts. An NGO now gets one, same as a funder.
- **`catalog_tools.py:331-338`** — the hardcoded "orgs has no writer yet" paragraph in
  `research_goals` goes. Also fix two stale strings in `promote_research`'s docstring
  (`:395`, `:402-404`: "Only identity, identifier and csr_year findings can move") and the
  closing grant paragraph at `:449-452`. Render `[org:N]` beside `[funder:N]`.
- **Three skills**: `catalog-mapping` (`:34-37`), `catalog-write-report` (`:47-57` and the
  Never line at `:63`, "Never describe an NGO's saved research as 'added to the catalog'"),
  `ngo-brief-for-funders` (`:61-65`).

**Exit gate:** `pytest -m "not integration"` green, including the parametrised test holding
each subagent spec against its own prompt; a live org run launches a catalog-writer whose
dossier read-back agrees with what it wrote.

---

## M5 — the screen and the docs

- `frontend/features/ingest/components/SubagentBoard.tsx:72` — `parsed.funder_name ??
  parsed.slug` becomes the new field.
- `frontend/features/ingest/lib/milestones.ts:163` — "the funder page links it" is wrong for
  an NGO brief.
- `frontend/features/ingest/components/ReviewQueue.tsx:10` — "resembled a funder already in
  the catalog" now has an org case.
- `docs/INGEST.md` — the "Known gaps" org entry (`:333-340`) is closed; the concept→table map
  (`:226`, `:232-238`) loses five "no writer" marks.
- `docs/DATA_PLATFORM.md:296,302,322,326` and `CLAUDE.md` — same sentence, same correction.

**Exit gate:** `npm run lint && npm run build` clean; no grep hit for "orgs has no writer"
outside this plan doc and the architecture doc's historical record.

---

## Verification

```bash
make up
cd backend && pytest -m "not integration" && ruff check .
cd frontend && npm run lint && npm run build
```

**The acceptance test is already in the database.** Promote the saved Goonj row and expect:

| Table | Expected |
|---|---|
| `orgs` | 1 added — `legal_form` "Registered Society (Societies Registration Act)", slug `goonj` |
| `org_identifiers` | 3 — fcra, pan, csr1 |
| `org_locations` | 8 — South Delhi `registered`, seven states `operates` |
| `documents` | 7, under `orgs/goonj/` |
| `contacts` | 6 · `programs` 5 · `metrics` 2 |
| `org_financials` | 0, reported as a research gap — that run found no figures |
| held | Goonj's website, as unstorable |

```sql
select 'orgs', count(*) from orgs where slug='goonj'
union all select 'ids',   count(*) from org_identifiers i join orgs o on o.id=i.org_id where o.slug='goonj'
union all select 'locs',  count(*) from org_locations l   join orgs o on o.id=l.org_id where o.slug='goonj'
union all select 'docs',  count(*) from documents d       join orgs o on o.id=d.org_id where o.slug='goonj';
select resolved_org_id from entity_research where slug='goonj';
select registered_location_id from orgs where slug='goonj';
```

Then **re-promote the same row** — every status must be `matched`, no row count moves.

Then a live run from `/import` on one NGO that is already in the cohort (e.g. `THE ANT`) to
exercise fill-blanks-only: its `legal_form` must be unchanged afterwards, with the difference
reported rather than applied.

**One caveat that is not this PR's to fix.** The run screen still under-reports, because
AG-UI drops subagent tool results (`OnToolEnd received non-ToolMessage output ('dict')`).
Verify this work against the database and the catalog-writer's own report, not the milestones
strip.

---

## Out of scope

- **`credential_events`** — 12A/80G/FCRA dates and cancellations. No migration needed, but a
  new finding model, prompt section and hand-rolled dedupe (the table has no UNIQUE key), and
  it yields nothing for research already saved.
- **The seven NGO fields with no column**, and `orgs.website`. Migration `0021`, a second PR.
- **A grant writer.** Unblocked by this, not built by it.
- **`repositories/orgs.py::get_org` does not read `org_financials`**, so promoted figures
  will not appear on `/orgs/<slug>` until it does. Small, separable.
- **The AG-UI dispatch bug** and **Langfuse 401s**.
