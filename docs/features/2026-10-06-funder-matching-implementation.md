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
- **Stubs at the end:** M3–M6. Each gets its own plan section when the previous milestone lands,
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
| R4 | **`area` fails only on stated geography.** A funder with `funder_locations` rows (role ≠ `registered`) and no overlap → *fail*. A funder with footprints alone and no overlap → *unknown*, `no_overlap_observed`. | footprints are sparse: spending elsewhere is not a statement that it won't fund here |
| R5 | **`statutory` applies to `funder_type IN (corporate_csr, corporate_foundation)`.** M6 revisits this. | the real values; `section_135_bound` is NULL for 30 of 43 |
| R6 | **`cvs` waits for M4** (it needs the doc vocabulary) and **`turnover` for M5** (it needs `requirement_code`). Their weight moves: governance becomes `board` 10, financial becomes `audits` 15. The total stays 100. | the loader refuses a doc type or selector that does not exist yet |
| R7 | **`projects_3` reads `org.projects`.** These are grants with `org_id` set, and org-owned programmes. A project is complete when funder, amount, theme, duration and results are all present. | the weights commit named the check but no evidence row |
| R8 | **Evidence is a typed bundle** (`OrgEvidence`, `FunderEvidence`), not a flat list of records. Each evaluator still declares its `reads`, and the resolver loads only the kinds that are read. | typed fields make the pure evaluators readable and their tests small |
| R9 | **Programme themes are backfilled by a CLI command** (`backfill-programme-themes`) into `program_tags`, with `is_inferred=true` and `tagged_by='taxonomy.clause_for'`. | `ingest/writer.py` writes no programmes, so there is no writer to hook |
| R10 | **`check_blocked` is skipped when picking a credential's latest event.** A `registered` in 2020 followed by `check_blocked` in 2025 still reads as registered. | the check could not run, so it says nothing either way |
| R11 | **Every org place counts**, whatever its role, plus `orgs.registered_location_id`. On both sides, a `valid_to` in the past drops the row. The registered-office exclusion (R4) is funder-side only. | an NGO's registered district is where it works; a funder's head office is not where it gives |

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
    queries. Counted by wrapping `conn.execute`.
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

## Later milestones (detailed when the previous one lands)

| | ships | exit gate |
|---|---|---|
| M3 | Funder-side tools `match_funders`, `explain_match`, `get_org`, `get_funder` and `find_funders` in `agent/tools/{match,profile}_tools.py`. The routing rule replaces prompt rules 11–19. Tool pins go from 6 to 11. A test that no tool module contains SQL. Labels in `toolLabels.ts`. | One tool call per job in the eval trace. Canary evals pass. |
| M3c | `match_orgs` and `find_orgs`; `shortlist_orgs` in the service. Pins go from 11 to 13. | A property test that both directions agree for every pair. |
| M3b | The `/skills/` route for Ask Sangam, plus five presentation skills. | The skill is read in the trace, and no write tool is reachable. |
| M4 | A Vault `doc_type` vocabulary plus fiscal year. `cvs` returns. | An uploaded certificate flips `recorded` → `on_file`. |
| M5 | `funder_eligibility.requirement_code` and `params`. `turnover` returns, with weights rebalanced. | HDFC's recorded bar drives `turnover`. |
| M6 | A `funder_type` vocabulary and type profiles. | An `international` funder gates on FCRA. |
