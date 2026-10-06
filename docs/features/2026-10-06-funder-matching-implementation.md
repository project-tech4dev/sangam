# Funder matching engine: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** a deterministic matching engine, behind a CLI, that ranks every funder for an org with
met / fail / unknown checks and a weighted score range. M1 and M2 of the engine doc.

**Architecture:**
- **Stage 1** is one SQL query. It returns one compact row per funder: what the funder shares
  with the org.
- **Stage 2** loads evidence once per kind, for the org and for the funders that survive stage 1.
- **Evaluators** are pure functions. **The engine** combines them under the active criteria
  version, which is stored in `criteria_sets`.

**Tech stack:** Python 3.12, psycopg 3 (async), Pydantic 2, PyYAML, Postgres 16.

**Spec:** `docs/features/2026-10-06-funder-matching-engine.md` (Draft v3). Evals:
`docs/features/2026-10-06-funder-matching-evals.md`.

**Scope:**
- **Written as full tasks:** M1 and M2. They ship together as one PR, because M1 alone ranks
  nothing.
- **M3** is written as Tasks 9–14 after M2 landed. It goes on the same branch.
- **Stubs at the end:** M3c–M6. Each gets its own plan section when the previous milestone lands,
  because M4, M5 and M6 each add schema that the earlier code then reads.

**Branch:** `feat/matching-engine`, cut from `docs/funder-cso-matching`. The PR targets
`docs/funder-cso-matching`, not `master`.

## Global constraints

- Schema changes go in `db/migrations/0023_criteria_sets.sql`, never in `db/init/`.
- A new live table is either catalogued or listed in `KNOWN_EXCLUDED`. `criteria_sets` is engine
  config, so it is excluded.
- Unit tests never touch a database. Anything that does carries `pytest.mark.integration` and uses
  the `db` fixture, which rolls back.
- Only positive evidence against the bar produces `fail`.
- Money is in rupees, never crore.
- Ruff line length is 110. Docstrings and comments are 1–2 lines.
- `python -m app.matching` runs outside the app lifespan. It reads `DATABASE_URL` the way
  `app/db/migrate.py` does.

## Rulings made against today's data

| # | ruling | why |
|---|---|---|
| R1 | **Org places walk up**: a district also counts as its parent state. KABIL has only Udalguri (district) and is matched on Assam as well. | the district → state → country chain is complete (132/132, 34/34) |
| R2 | **Funder places walk up the same way.** A funder district in Kamrup shares *state* Assam with KABIL. | otherwise state-level overlap is invisible whenever a funder records only districts |
| R3 | **`area` levels**: district 1.0, state 0.6, `pan_india_stated` (a `funder_locations` row at India, the country) 0.3. **Region** (Northeast India) gives *unknown*, `region_membership_not_recorded`. | no table records which states a region contains |
| R4 | **`area` fails only on stated geography: `funder_locations` rows with role `funds`.** No overlap with those → *fail*. `operates`, `priority` and footprints with no overlap → *unknown*, `no_overlap_observed`. Any non-registered row still counts toward overlap, pan-India and regions. *(Amended after review: `operates` is where a plant is and `priority` is a preference; neither says it won't fund elsewhere.)* | footprints are sparse: spending elsewhere is not a statement that it won't fund here |
| R5 | **`statutory` applies to `funder_type IN (corporate_csr, corporate_foundation)`.** M6 revisits this. | the real values; `section_135_bound` is NULL for 30 of 43 |
| R6 | **`cvs` waits for M4** (it needs the doc vocabulary) and **`turnover` for M5** (it needs `requirement_code`). Their weight moves: governance becomes `board` 10, financial becomes `audits` 15. The total stays 100. | the loader refuses a doc type or selector that does not exist yet |
| R7 | **`projects_3` reads `org.projects`.** These are grants with `org_id` set, and org-owned programmes. A project is complete when funder, amount, theme, duration and results are all present. | the weights commit named the check but no evidence row |
| R8 | **Evidence is a typed bundle** (`OrgEvidence`, `FunderEvidence`), not a flat list of records. Each evaluator still declares its `reads`, and the resolver loads only the kinds that are read. | typed fields make the pure evaluators readable and their tests small |
| R9 | **Programme themes are backfilled by a CLI command** (`backfill-programme-themes`) into `program_tags`, with `is_inferred=true` and `tagged_by='taxonomy.clause_for'`. | `ingest/writer.py` writes no programmes, so there is no writer to hook |
| R10 | **`check_blocked` is skipped when picking a credential's latest event.** A `registered` in 2020 followed by `check_blocked` in 2025 still reads as registered. | the check could not run, so it says nothing either way |
| R11 | **Every org place counts**, whatever its role, plus `orgs.registered_location_id`. On both sides, a `valid_to` in the past drops the row. The registered-office exclusion (R4) is funder-side only. | an NGO's registered district is where it works; a funder's head office is not where it gives |
| R12 | **The shortlist has three blocks.** Any gate *fail* → *did not pass*. Otherwise the `fit` group *unknown* → *not enough recorded*. Everything else is ranked, including *unverified*. | the spec names the blocks but not the line between them; a funder we cannot place or theme cannot be ranked against one we can |
| R13 | **Inferred tags never produce *fail*.** `theme` and `prog` fail only on tags with `is_inferred = false`. Inferred-only tags give *unknown* `funder_themes_inferred_only` / `funder_programmes_inferred_only`; a shared inferred clause still counts as *met*. | 34 of 48 funder tags and every backfilled programme tag are classifier output, and a classifier is not positive evidence |
| R14 | **An unrecorded `funder_type` keeps every `funder_type`-scoped check.** For 4 funders, statutory runs and is mostly *unknown* → *unverified*. | skipping it made "type not recorded" read as *passed* and rank above every CSR funder |
| R15 | **Credential conflicts are *unknown*.** A lapsed event alongside a current identifier or a Vault certificate → `conflicting_evidence`. `superseded` is not lapsed (12A → 12AB). An active event past its `valid_until` → `validity_ended`. | only positive, uncontradicted evidence against the bar may fail |
| R16 | **A check that does not apply leaves the denominator.** A private foundation is scored out of 60 (fit, governance, programme), a CSR funder out of 100. Kept: *passed* versus *unverified* sorts before the score, so a CSR funder with statutory unknowns never competes with one on score alone. | the spec says not-applicable checks drop out; scaling them in would charge a foundation for law it is not bound by |

## File structure

| file | responsibility |
|---|---|
| `backend/app/matching/models.py` | Pydantic outputs: `CheckResult`, `CategoryScore`, `Assessment`, `Shortlist`, `FunderRef`, `OrgRef` |
| `backend/app/matching/evidence.py` | `OrgEvidence`, `FunderEvidence`, `PairFit` dataclasses, plus the async loaders and the stage-1 `FIT_SQL` |
| `backend/app/matching/evaluators.py` | the `@evaluator` registry and the eight evaluators (pure) |
| `backend/app/matching/config.py` | the criteria schema, `parse_criteria(dict)`, `load_yaml(path)` and every refusal |
| `backend/app/matching/engine.py` | pure: `assess(criteria, org, funder) -> Assessment`, combinators, roles, `applies`, weights, ranking key, gaps |
| `backend/app/matching/registry.py` | `criteria_sets` lifecycle: `load_draft`, `activate`, `get(ref)`, `list_sets` |
| `backend/app/matching/themes.py` | `backfill_programme_themes(conn)` |
| `backend/app/matching/service.py` | `shortlist`, `assess`, `assess_many`, `resolve` over a connection |
| `backend/app/matching/__main__.py` | CLI: `load`, `activate`, `sets`, `match`, `explain`, `backfill-programme-themes` |
| `backend/app/matching/criteria/funder_matching.yaml` | criteria v1 |
| `db/migrations/0023_criteria_sets.sql` | the table plus a partial unique index on `active` |
| `backend/tests/test_matching_{evaluators,config,engine}.py` | unit tests |
| `backend/tests/test_matching_integration.py` | resolver, stage 1, registry, service, query count |

## Interfaces (shared by every task)

```python
Outcome = Literal["met", "fail", "unknown"]
Basis = Literal["recorded", "on_file", "not_researched", "searched_not_found", "not_on_file", "not_applicable"]

@dataclass(frozen=True)
class Check:                      # an evaluator's return value
    outcome: Outcome; basis: Basis; reason_code: str
    reason_params: dict = field(default_factory=dict)
    cites: tuple[str, ...] = (); level: str | None = None   # a `partial` level, e.g. "district"

Evaluator = Callable[[OrgEvidence, FunderEvidence | None, BaseModel], Check]
REGISTRY: dict[str, EvaluatorSpec]  # name -> (fn, reads: frozenset[str], params: type[BaseModel], levels)

def assess(criteria: Criteria, org: OrgEvidence, funder: FunderEvidence) -> Assessment
def rank_key(a: Assessment, keys: list[str]) -> tuple
async def load_org(conn, org_id, reads) -> OrgEvidence
async def load_fit(conn, org: OrgEvidence) -> dict[int, FunderEvidence]      # stage 1, one query
async def enrich_funders(conn, funders: dict[int, FunderEvidence], reads) -> None   # stage 2
```

## Review focus

1. **An org with nothing recorded** (no places, no tags): every fit check is *unknown*, the score
   is 0–100, and the funder sits in `not_enough_recorded`. Never *fail*, never a score of 0.
2. **A funder with nothing recorded:** the same result, on the funder side.
3. **An org whose only place is a district** (KABIL): it still matches funders that record only
   the state (R1).
4. **Two funders with identical evidence:** the tie breaks on `funder_id`, and the order is the
   same every run.
5. **A YAML whose weights total 99**, or one that names a check it does not define: `load`
   refuses it, and nothing is written to `criteria_sets`.

---

### Task 1: models and the evaluator registry

**Files:** create `matching/__init__.py`, `models.py`, `evidence.py` (the dataclasses only),
`evaluators.py` (the registry plus `has_identifier`). Test: `tests/test_matching_evaluators.py`.

- [ ] Write failing tests:
  - `has_identifier(12a)` on an empty `OrgEvidence` → `unknown / not_researched`.
  - A current `org_identifiers` fact → `met / recorded`, cites `[org:9]`.
  - The latest credential event `cancelled` → `fail / recorded`, `reason_code="cancelled"`.
  - The latest event `not_found`, or a research `not_found` entry naming "12A" → `unknown /
    searched_not_found` with `reason_params.searched_on`.
  - A Vault document of the matching type (`uploaded_by` set) → `met / on_file`.
- [ ] Run: `pytest tests/test_matching_evaluators.py -q`. Expected: ImportError.
- [ ] Implement the dataclasses, `@evaluator(name, reads=, params=, levels=)` and `has_identifier`.
- [ ] Run. Expected: pass. Commit `feat(matching): evidence bundle, evaluator registry, has_identifier`.

### Task 2: the remaining evaluators

**Files:** `evaluators.py`. Test: the same file.

`shares_place`, `shares_theme`, `shares_programme_theme`, `min_audited_years`, `min_board`,
`has_document`, `min_projects`.

- [ ] Write failing tests, one per row:

| evaluator | case | expected |
|---|---|---|
| shares_place | shared district | met, level `district` |
| shares_place | shared state only | met, level `state` |
| shares_place | funder stated pan-India | met, level `pan_india_stated` |
| shares_place | funder stated places, none shared | fail, `no_overlap_stated` |
| shares_place | funder footprints only, none shared | unknown, `no_overlap_observed` (R4) |
| shares_place | funder region only | unknown, `region_membership_not_recorded` (R3) |
| shares_place | org has no places | unknown, `org_places_not_recorded` |
| shares_theme | a shared clause | met, cites the clause label |
| shares_theme | funder tags, none shared | fail, `no_shared_theme` |
| shares_theme | funder untagged, or org untagged | unknown |
| shares_programme_theme | shared, none shared, no tagged programmes | met / fail / unknown |
| min_audited_years(3) | 3 audited years | met |
| min_audited_years(3) | 1 audited year | unknown, `{have: 1, need: 3}`; fewer recorded years is not fewer audits |
| min_board(3) | 2 office bearers | fail, `count_short {have: 2, need: 3}` |
| min_board(3) | 0 office bearers | unknown |
| has_document(x) | vault / research / none | met on_file / met recorded / unknown |
| min_projects(3) | 3 complete projects | met |
| min_projects(3) | 1 complete, 2 missing results | unknown, `{complete: 1, need: 3}` |

- [ ] Run. Expected: fail. Implement. Run. Expected: pass.
- [ ] Commit `feat(matching): place, theme, programme, audit, board, document and project evaluators`.

### Task 3: criteria schema and loader

**Files:** `config.py`, `criteria/funder_matching.yaml`, and `pyyaml>=6` added to
`backend/pyproject.toml`. Test: `tests/test_matching_config.py`.

- [ ] Write failing tests:
  - `funder_matching.yaml` loads.
  - Each of the following is refused with a message naming the offending part:
    - an unknown evaluator;
    - a param that fails the evaluator's params model;
    - a group cycle;
    - a code defined twice;
    - an unknown `applies` selector;
    - an unknown ranking key;
    - weights not totalling 100;
    - a category weight ≠ the sum of its checks;
    - a weight on an undefined check;
    - a `partial` level the evaluator doesn't emit;
    - `engine` ≠ `ENGINE_API`.
  - `content_hash` is stable across key order.
- [ ] Run. Expected: fail.
- [ ] Implement `Criteria`: `checks`, `groups` (`all` / `any` / `min_met` + `of`), `roles`,
  `applies`, `weights`, `partial`, `ranking`. Also `parse_criteria(raw: dict) -> Criteria`,
  `load_yaml(path) -> tuple[Criteria, dict]` and `content_hash(raw) -> str` (sha256 of
  canonical JSON).
- [ ] Write the YAML: v1 per the spec §3, minus `cvs` and `turnover` (R6), with
  `statutory.applies` per R5.
- [ ] Run. Expected: pass. Commit `feat(matching): criteria schema and loader that refuses bad files`.

### Task 4: the engine — combinators, roles, applies, weights, ranking

**Files:** `engine.py`. Test: `tests/test_matching_engine.py`.

- [ ] Write failing tests:
  - Truth tables for `all`, `any` and `min_met`, over every met/fail/unknown combination of
    three members.
  - A gate fail → `failed`; a gate unknown → `unverified`; otherwise `passed`.
  - A check whose `applies` doesn't match gets basis `not_applicable` and drops out of the
    applicable weight.
  - The worked example from spec §3 reproduced exactly: met 47, applicable 95 → `score_min` 49,
    `score_max` 100, coverage 49.
  - Partial credit: a state-level area earns 12 of 20.
  - A funder with zero evidence → 0–100, never 0.
  - `gaps` ordering: gate first, then by weight (largest first); `fail` before `unknown`.
  - Ranking: passed before unverified; then `score_min`, `coverage`, `shared_districts`;
    `funder_id` last.
  - The same inputs give byte-identical `Assessment` JSON.
- [ ] Run. Expected: fail. Implement `assess`, `rank_key`, `combine`. Run. Expected: pass.
- [ ] Commit `feat(matching): engine with three-valued groups, gates and a weighted score range`.

### Task 5: migration, registry, programme-theme backfill

**Files:** `db/migrations/0023_criteria_sets.sql`, `registry.py`, `themes.py`, and
`KNOWN_EXCLUDED += {"criteria_sets"}` in `catalog.py`. Test: `tests/test_matching_integration.py`
(integration).

- [ ] Write failing integration tests:
  - `load_draft` inserts `draft` with the hash and the git sha.
  - Loading the same content twice returns the existing version and does not duplicate it.
  - `activate(v)` retires the previously active row in the same transaction.
  - There is at most one active row per set; the unique index enforces it.
  - `get(ACTIVE)` returns the active row. Before any activation it raises `NoActiveCriteria`.
  - A rollback is a re-activation.
  - `backfill_programme_themes` tags a programme whose text matches a clause, and is idempotent
    on a second run.
- [ ] Run against compose Postgres after `make migrate`. Expected: fail.
- [ ] Implement. Run. Expected: pass.
- [ ] Commit `feat(matching): criteria_sets lifecycle and programme-theme backfill`.

### Task 6: evidence resolver and stage-1 SQL

**Files:** `evidence.py` (the loaders and `FIT_SQL`). Test: the integration file.

- [ ] Write failing integration tests, all on synthetic orgs and funders inserted inside the
  rolled-back transaction:
  - `load_org` reads places with their parent states, clauses (via `maps_to`), identifiers,
    events, financials, board, documents, projects and `not_found`.
  - `load_fit` returns one row per funder, with shared districts, states, pan-India, region
    flags, stated vs observed place counts, and shared tag and programme clauses.
  - **Query count:** with 200 synthetic funders, `load_fit` + `enrich_funders` issue ≤ 6
    queries, counted by wrapping `conn.execute`. Today that is 1, because `enrich_funders` loads
    nothing until M5. A whole shortlist is about 12 (criteria 1, org 1 + 9 kinds, stage 1); the
    claim is that this stays constant as funders grow.
- [ ] Run. Expected: fail. Implement. Run. Expected: pass.
- [ ] Commit `feat(matching): evidence resolver and one-query stage 1`.

### Task 7: service and CLI

**Files:** `service.py`, `__main__.py`, Makefile targets `criteria-load`, `criteria-activate`,
`criteria-sets`, `match`, `match-explain`, `programme-themes`. Test: the integration file.

- [ ] Write failing integration tests:
  - `shortlist` puts a synthetic org with a district match on top, and puts a no-evidence funder
    in `not_enough_recorded`.
  - `assess_many` keeps the order the ids were given.
  - `resolve("org", "kabil")` returns the org; an ambiguous string returns candidates.
  - The CLI `match --org kabil` exits 0 and prints the criteria version.
- [ ] Run. Expected: fail. Implement. Run. Expected: pass.
- [ ] Verify on real data: `make migrate && make criteria-load && make criteria-activate VERSION=1
  && make programme-themes && make match ORG=kabil`.
- [ ] Commit `feat(matching): service and CLI`.

### Task 8: whole-branch check

- [ ] `pytest -m "not integration"` and `pytest -m integration`: no new failures over the
  baseline. Seven integration failures predate this work: `test_migration_integrity` ×3 and
  `test_storage` ×4, all local-data dependent.
- [ ] `ruff check .`
- [ ] Update `CLAUDE.md`: add `matching/` to the layout, and add the new make targets.

---

## M3: funder-side tools in Ask Sangam

**Goal:** a person asking Ask Sangam *"Which funders fit KABIL?"* gets the engine's answer in one
tool call. The model no longer writes the funnel's SQL itself.

**Exit gate:** in the eval trace, each job takes one tool call, and `make evals TAG=canary`
passes. Evals cost money, so ask before running them.

### M3 rulings

| # | ruling | why |
|---|---|---|
| R17 | **`get_funder` comes back, without the flaw that removed it.** It renders `load_funder`, the funder-side twin of `load_org`, and has no query of its own. The old `get_funder` was a separate, curated query. | `CLAUDE.md` removed four lookups because each was a second reader of the same rows. A profile drawn from the engine's own bundle is that one reader, not a second one. |
| R18 | **Agent text is rendered in `app/agent/tools/match_render.py`, not in `app/matching/`.** The CLI keeps its own debug printout, which shows raw codes. | the two readers differ: a person debugging criteria wants codes, while the model wants phrases. `test_prompt._LITERAL` also scans `agent/tools/*.py` for markers, so new f-string markers there stay guarded. |
| R19 | **Tools take names, not ids.** Each one resolves its text through `service.resolve`. An `Ambiguous` result returns the candidates, each cited, plus an instruction to ask which one was meant. It never picks. | the user says "KABIL", not 9. Resolving inside the tool keeps the job at one call. |
| R20 | **`find_funders` is stage 1 run against a stated profile.** Place and theme names resolve to `locations` and clause slugs and become an `OrgEvidence`. `load_fit` runs, and only `shares_place`, `shares_theme` and `shares_programme_theme` are applied. Each funder lands in one of three blocks: *matches* (every dimension asked about is met), *not recorded* (none fail, at least one unknown), and *no overlap*, which is a count only. A term that does not resolve is an error naming near candidates, never dropped silently. | "gives in Assam" then has one definition, the `area` evaluator's. No org means no statutory checks. |
| R21 | **A theme dimension is met when either the theme check or the programme check is met** (Kleene `any`). | a funder that tags nothing but runs a livelihoods programme still gives to livelihoods |
| R22 | **An open call is `rfps.status = 'open'`.** A deadline already passed is shown as passed, not hidden. | today 3 calls are listed open, and both recorded deadlines (latest 7 Jul 2026) have passed. Hiding them would read as "no calls ever". |
| R23 | **The no-SQL test bans query text and engine internals, not imports in general.** Tool modules contain no `SELECT`, `FROM` or `execute(`, and import nothing from `matching.evidence`, `engine` or `registry`. | they still need `@tool` and `get_pool`. "Import only the service" was too strict to write as a test. |

### Task 9: funder profile and stated-profile search in the service

**Files:** `evidence.py` (`load_funder`, `stated_profile`), `models.py` (`FunderProfile`,
`OrgProfile`, `FunderMatch`, `FunderList`), `service.py` (`profile`, `find_funders`). Test: the
integration file.

**Produces:**
```python
async def load_funder(conn, funder_id: int) -> FunderProfile   # LookupError if unknown
async def stated_profile(conn, places: list[str], themes: list[str]) -> OrgEvidence  # ValueError names candidates
async def profile(conn, kind: Literal["org", "funder"], ref_id: int) -> OrgProfile | FunderProfile
async def find_funders(conn, *, places=(), themes=(), funder_types=(), limit=20, offset=0) -> FunderList
```

The `FunderProfile` fields and the columns behind each:

| field | source |
|---|---|
| `funder` | `funders` id, name, slug, funder_type, website, section_135_bound |
| `places` | `funder_locations` (role, location name and kind, valid_to filter), with `registered` kept separate |
| `footprints` | `funder_footprints`: a count of districts and states, plus the latest `fiscal_year` |
| `themes` | `funder_tags` → clause via `_CLAUSE_JOIN`, each with `is_inferred` |
| `programmes` | `programs` where `funder_id = %s`: the count by kind, plus names with their clause |
| `requirements` | `funder_eligibility` (kind, criterion). An empty list renders "no eligibility bars recorded" |
| `csr_years` | `funder_csr_years`, latest three: fiscal_year, prescribed_csr, total_spent (rupees) |
| `spend` | `funder_csr_spend`: total by state and by sector, top five each, plus a row count |
| `partners` | `funder_partners`: a count by partner_kind, plus the first ten names, cited `[org:N]` when `org_id` is set |
| `calls` | `rfps` where status = 'open': title, deadline, amount_min/max, url (R22) |

`OrgProfile` is `OrgEvidence` with every org kind loaded, plus the registered location.

- [ ] Write failing integration tests on synthetic rows:
  - `load_funder` fills every field.
  - A funder with no rows anywhere gives empty fields, never `None`, and renders "not recorded".
  - `stated_profile(["assam"], [])` resolves case-insensitively. A district also adds its
    parent state (R1).
  - `stated_profile(["Atlantis"], [])` raises `ValueError` naming near matches.
  - `find_funders(places=["Udalguri"])` puts a district funder first, a state funder second
    with level `state`, a no-rows funder in `not_recorded`, and a `funds`-elsewhere funder in
    the `no_overlap` count.
  - `funder_types=["corporate_csr"]` excludes other types. A funder whose type is not recorded
    goes to `not_recorded`, because the type is a dimension like place and theme and is *unknown*
    for it. It is never excluded silently. *(Ruling while implementing: this replaces a separate
    `type_not_recorded` count, so all three dimensions follow one Kleene rule.)*
  - Query count: `find_funders` issues at most 4 queries at 200 funders.
- [ ] Run. Expected: fail. Implement. Run. Expected: pass.
- [ ] Commit `feat(matching): funder profile and stated-profile search`.

### Task 10: rendering for the model

**Files:** `app/agent/tools/match_render.py`. Test: `tests/test_match_render.py`, unit only, on
hand-built models.

**Produces:** `render_shortlist(Shortlist)`, `render_assessments(list[Assessment])`,
`render_org(OrgProfile)`, `render_funder(FunderProfile)`, `render_funders(FunderList)`,
`render_ambiguous(Ambiguous)`. Each returns `str` capped at `sql/render.MAX_OUTPUT_CHARS`, and a
cap says what was cut.

Rules each renderer keeps:
- Every funder and org line carries its marker. Check lines carry their evidence `cites`.
- A score reads `score 67–100 (coverage 67%), computed by Sangam, criteria v1`.
- The three shortlist blocks are always printed with their counts, and *not enough recorded*
  names every funder in it.
- An unknown reads by basis: *not recorded*, *searched, not found (date)* or *not on file*. It
  never reads *fail*.
- Money is shown in rupees with the lakh/crore grouping (`₹12,00,000`), so the model copies
  figures rather than converting them.
- `REASONS` maps each `reason_code` to a phrase.

- [ ] Write failing tests:
  - Each renderer's markers.
  - The three blocks always print.
  - An unknown never prints "fail".
  - The budget is cut with a note.
  - `test_every_reason_code_has_a_phrase` scans the `reason_code` literals and the
    `_ACTIVE`/`_LAPSED` values in `evaluators.py` against `REASONS`.
  - `test_prompt.test_tools_emit_the_markers_we_think_they_do` still passes.
- [ ] Run. Expected: fail. Implement. Run. Expected: pass.
- [ ] Commit `feat(agent): render match results for the model`.

### Task 11: the five tools, registered

**Files:**
- `app/agent/tools/match_tools.py`: `match_funders(org, limit=10)` and
  `explain_match(org, funders)`, one to three funders.
- `app/agent/tools/profile_tools.py`: `get_org(org)`, `get_funder(funder)` and
  `find_funders(places, themes, funder_types, limit=20)`.
- `app/agent/build.py`: `TOOLS` grows to 11, and the comment is rewritten (R17).
- `frontend/features/ask/lib/toolLabels.ts`: five labels.

Each tool body:
1. `async with get_pool().connection() as conn`.
2. Resolve.
3. Make one service call.
4. Render.
5. `except Exception as exc: return f"<tool> failed: {exc}"`.

The tools hard-code `ACTIVE` criteria.

**Tests:**
- `tests/test_match_tools.py`, unit: monkeypatch `service.*` and `get_pool`.
- `tests/test_harness.py:106`: the pin becomes 11 tools plus `read_file`.
- `tests/test_tools_registered.py`: the package walk plus R23.

- [ ] Write failing tests:
  - An ambiguous org returns candidates and calls no matching function.
  - A service `LookupError` comes back as a `"<tool> failed:"` string.
  - Every `@tool` in `app/agent/tools/` is in `TOOLS`.
  - R23 holds for `match_tools.py` and `profile_tools.py`.
  - `explain_match` with four funders returns an error string.
  - The pin is updated.
- [ ] Run. Expected: fail. Implement. Run. Expected: pass. Then `npm run lint` in `frontend/`.
- [ ] Commit `feat(agent): match_funders, explain_match, get_org, get_funder, find_funders`.

### Task 12: the routing rule replaces the funnel procedure

**Files:** `app/agent/instructions.md`, `tests/test_prompt.py`, `CLAUDE.md`.

The prompt changes in three places:
- **The preamble's "write SQL" sentence** is narrowed. Judgements of fit, eligibility and rank
  go to the matching tools.
- **"Every data question is answered by writing SQL"** becomes "every question the tools below
  do not cover".
- **Rules 11–19 become rules 11–15:**
  - 11: route by job (the §1b table).
  - 12: never re-derive a judgement or a profile field in `db_query`.
  - 13: ambiguous means ask, never pick.
  - 14: reading a result — the three blocks, unknown is never ineligible, and say the criteria
    version.
  - 15: gaps — in the tool's order, and never invent a bar, number or document.

Two existing rules are adjusted to fit:
- Rule 2's computed-figure exception names the match score range.
- Rule 4 still covers stored `fit_scores`.

`test_prompt.py` changes:
- Delete: `TestFunderShortlistProcedure`, `TestFunderAssessmentProcedure`,
  `TestShortlistGeographyAndLimits` and `TestAssessmentArithmetic`.
- Add `TestRouting`, which asserts:
  - each tool is named in the routing rule;
  - "never" appears in the re-derive rule;
  - "not enough recorded" and "criteria version" appear in rule 14;
  - "no eligibility bars recorded" appears.

`CLAUDE.md`:
- "exactly six tools" becomes eleven, with the list.
- One paragraph explains R17: judgements have one home, and profiles read the engine's bundle.
- The architecture diagram's tool list is updated.

- [ ] Write the new prompt tests. Run them. Expected: fail. Edit the prompt. Run. Expected: pass.
- [ ] Run `pytest -m "not integration"` in full: `test_sql_compare` reads the prompt too.
- [ ] Commit `feat(agent): route judgements to the matching tools`.

*(Ruling while implementing: Tasks 11 and 12 ship as one commit. Registering the tools makes
`test_prompt_names_every_registered_tool` fail until the prompt names them, so committing
them separately would leave one commit red.)*

### Task 13: eval trajectory gates (E4, minus skills)

**Files:**
- `tests/evals/harness.py`: `run_agent` returns the tool calls. `CaseResult` gains
  `tools: list[str]` and `tool_text: str`. `score()` gains four gates: `expected_tools`,
  `forbidden_tools`, `max_tool_calls` and `faithful_to_tool`. `skills_read` waits for M3b.
- `tests/evals/test_harness_gates.py`: new; no model, no database.
- `tests/evals/cases/matching.jsonl`: new.
- `golden.jsonl`: lines 11–14 leave it.
- `tests/evals/test_sql_compare.py`: `test_no_case_forbids_a_phrase_the_prompt_teaches` reads
  every `cases/*.jsonl`.

`faithful_to_tool` fails in two cases:
- the answer has a `[funder:N]` or `[org:N]` that no tool result contained;
- the answer has a `₹` figure that no tool result contained.

The cases come from the evals doc table, keeping only those whose tools exist after M3:
- canaries: `shortlist-one-call`, `shortlist-unknowns-named`, `profile-one-call`,
  `find-funders-by-place`, `no-threshold-invented`;
- others: `readiness-unknown-not-ineligible` (without `skills_read`), `criteria-version-stated`,
  `ambiguous-org`, `fact-stays-sql`.

What happens to the four cases moved out of `golden.jsonl`:
- `shortlist-unrankable-named` folds into `shortlist-unknowns-named`. It no longer names HDFC:
  gate on behaviour, not on data.
- `shortlist-org-untagged` moves as-is, plus `expected_tools`.
- `assess-no-bars-recorded` moves, with `expected_tools: [get_funder]`.
- `assess-grant-size-unscorable` is deleted. It asserts the rubric's "available points", which
  the engine does not have.

- [ ] Write failing gate tests: each gate passes and fails on a hand-built `CaseResult`. Run.
  Expected: fail. Implement. Run. Expected: pass.
- [ ] Commit `test(evals): trajectory gates and matching cases`.

### Task 14: whole-branch check

- [ ] `pytest -m "not integration"` and `pytest -m integration`: no new failures over the seven
  in the baseline. `ruff check .` adds no new errors. `npm run build` in `frontend/`.
- [ ] Real data: through the dev backend, ask *"Which funders fit KABIL?"* once, and confirm the
  trace has one `match_funders` call. (This is one paid model call; it needs the user's yes.)
- [ ] Ask before `make evals TAG=canary`.

---

## Later milestones (detailed when the previous one lands)

| | ships | exit gate |
|---|---|---|
| M3 | Detailed above (Tasks 9–14). | One tool call per job in the eval trace. Canary evals pass. |
| M3c | `match_orgs` and `find_orgs`; `shortlist_orgs` in the service. Pins go from 11 to 13. | A property test that both directions agree for every pair. |
| M3b | The `/skills/` route for Ask Sangam, plus five presentation skills. | The skill is read in the trace, and no write tool is reachable. |
| M4 | A Vault `doc_type` vocabulary plus fiscal year. `cvs` returns. | An uploaded certificate flips `recorded` → `on_file`. |
| M5 | `funder_eligibility.requirement_code` and `params`. `turnover` returns, with weights rebalanced. | HDFC's recorded bar drives `turnover`. |
| M6 | A `funder_type` vocabulary and type profiles. | An `international` funder gates on FCRA. |
