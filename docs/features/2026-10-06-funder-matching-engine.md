# Funder matching: production architecture

> **Superseded 2026-10-06** by `2026-10-06-funder-matching-agentic.md`: matching moves from this
> deterministic engine to an assessor subagent whose prompt is the criteria. The engine was built
> through M3 and then removed; this file is kept for the reasoning.

*Draft v3 — 2026-10-06. v3: thirteen specific tools, one call per job (§1b); weighted score as a range (§3). Supersedes v1 of this file and the prompt-only design in `2026-10-05-funder-matching-in-ask-sangam.md`. Evals: `2026-10-06-funder-matching-evals.md`.*

## Context

Matching on branch `docs/funder-cso-matching` is a prompt procedure today (rules 11–19 in
`backend/app/agent/instructions.md`): the model writes the funnel's SQL afresh on every request.
The approved direction is a deterministic engine behind two tools, criteria in YAML, and skills that
only present. This document answers the review brief: whether the proposed shape is right for
production, and what changes so it stays extensible, deterministic and easy to maintain as funders
grow from 42 to 2,000.

**Verdict:** the proposed shape is right. It needs five changes:

1. **Split the criteria *store* from the criteria *engine*.** Versions with a lifecycle are their own
   component.
2. **Evaluators declare the evidence kinds they read.** The resolver loads each kind once, in bulk.
3. **A check outcome carries a *basis* next to its met / fail / unknown.** That gives the six
   evidence states the brief asks for without adding outcome values.
4. **Gates, ranking and advisories are *roles* on checks.** The combinators `all` / `any` /
   `min_met` use three-valued logic, so no expression language is needed.
5. **The service returns domain objects.** Rendering to text happens in the tool layer. Tests and
   evals assert on codes, not prose.

**Principle, unchanged:** agents handle uncertainty — intent, research, extraction, explanation.
Code handles decisions — eligibility, matching, ranking, thresholds. **No new LLM agent.** The only
candidate was a "matching agent", and it would re-introduce exactly the non-determinism this
replaces.

## Target architecture

```
                                   USER (Ask chat)
                                         │
┌─ ASK SANGAM AGENT ─────────────────────▼───────────────────────────────────────┐
│ understand intent · resolve which org/funder · pick a tool · explain result    │
│ instructions.md = constraints (always)   skills = presentation (on demand)     │
│ tools: match_funders · explain_match · get_org · get_funder · find_funders    │
│        ║ db_query · db_* · search_graph · fetch_url  (facts outside a profile) │
└──────────────┬─────────────────────────╨──────────────────────┬────────────────┘
               │ domain calls                                    │ factual follow-ups
┌─ MATCHING SERVICE  app/matching/service.py ────────────┐       │ (read-only SQL)
│ shortlist() · assess() · assess_many()                 │       │
│ returns Shortlist / Assessment objects, never text     │       │
│ other clients: CLI (make match), evals, REST later     │       │
└───────┬───────────────────────┬────────────────────────┘       │
        │                       │                                │
┌─ CRITERIA REGISTRY ──┐  ┌─ CRITERIA ENGINE ──────────┐  ┌─ EVIDENCE RESOLVER ──────┐
│ criteria_sets table  │  │ evaluators (pure, registry)│  │ declared evidence kinds  │
│ draft/active/retired │─►│ combinators all/any/min_met│◄─│ bulk load: org ×1,       │
│ YAML in git → load   │  │ roles gate/rank/advisory   │  │ candidates ×1 per kind   │
│ content_hash, git sha│  │ applies-to selectors       │  │ normalises → Evidence    │
└──────────────────────┘  │ deterministic ranking key  │  └──────────┬───────────────┘
                          └────────────────────────────┘             │
                                                                     ▼
┌─ POSTGRES (system of record) ──────────────────────────────────────────────────┐
│ org_identifiers · credential_events · org_financials · contacts · grants ·     │
│ programs/program_tags · documents (Vault) · org_locations · funder_* ·         │
│ funder_eligibility(+requirement_code, params) · entity_research(not_found) ·   │
│ criteria_sets                                                                  │
└──────────────▲───────────────────────────────────────────────▲─────────────────┘
               │ validated writes only                          │ typed upload
┌─ SANGAM IMPORT (research agent) ──────────┐        ┌─ VAULT (Ask workspace) ───┐
│ fuzzy: web research, PDF reading,         │        │ doc_type from vocabulary, │
│ extraction, requirement mapping, themes   │        │ fiscal year               │
│ → findings → DETERMINISTIC WRITERS/VALIDATORS      └───────────────────────────┘
└───────────────────────────────────────────┘
```

Changes from the brief's diagram: the registry is its own box; Vault and Import both write through
validators; the service has non-agent clients; and the generic tools stay a side path for facts, not
judgements.

## 1. Ask Sangam agent

| responsible for | explicitly not responsible for |
|---|---|
| reading intent: shortlist, one funder, comparison, readiness, or a plain fact | computing fit, eligibility, rank or any threshold |
| resolving which org and funder; asking when ambiguous (the service returns candidates) | turning *unknown* into *fail* or *not eligible*, or the reverse |
| choosing the tool, and making follow-up calls | re-deriving or "double-checking" a match in `db_query` |
| explaining the structured result, citing it, offering the next step | inventing a requirement, number or document the result does not contain |
| loading a skill to shape the write-up | changing criteria, or running a draft criteria version |

**Routing rule** (in `instructions.md`, a constraint, so not a skill):

> **The rule:** a question whose answer is a *judgement* about fit, eligibility or rank goes to a
> matching tool. A question about a *fact* goes to `db_query`.
> **Example:** *"Which funders fit KABIL?"* → `match_funders`. *"Where did HDFC spend in FY23?"* →
> `db_query`. *"Why is HDFC first?"* → `explain_match`, never a fresh SQL ranking.
> **Why it matters:** two paths to one judgement give two answers. The `search_orgs` lesson in
> `CLAUDE.md` applies in reverse here — the judgement gets one home, and facts keep theirs.

## 1b. Tool set — one call per job

**Verdict:** use specific tools, each **complete for its job**, and have all of them read through
the evidence resolver. Skills shape the write-up only. They never chain tools.

| job | tool | returns | service call |
|---|---|---|---|
| which funders can this NGO apply to | `match_funders(org, limit=10)` | ranked shortlist, the org's own gaps, counts of *did not pass* / *not recorded* | `shortlist` |
| why this funder, or how these 2–3 compare | `explain_match(org, funders)` | every check per funder and the ordered gaps; side by side when there is more than one | `assess_many` |
| tell me about this NGO | `get_org(org)` | places, themes, credentials, audits, board, Vault files; each field marked recorded or not recorded, with a citation | `profile("org")` |
| tell me about this funder | `get_funder(funder)` | where it gives, themes, programmes, requirements, spend, open calls | `profile("funder")` |
| funders giving in X for Y | `find_funders(places, themes, funder_types)` | the stage-1 fit query run against a stated profile, all matches plus counts | `find_funders` |
| which NGOs fit this funder | `match_orgs(funder, limit=10)` | ranked NGOs: the same checks, run in the other direction | `shortlist_orgs` |
| NGOs working in X on Y, holding Z | `find_orgs(places, themes, has)` | stage 1 over orgs; `has` filters on credentials (`12a`, `80g`, `csr1`, `audits_3y`) through their evaluators | `find_orgs` |
| any other fact | `db_query` (kept) | — | — |

The tools are symmetric: two per side (`get_*`, `find_*`), plus matching in both directions.
`explain_match` already takes one pair, so it serves both directions. *"Why does KABIL fit HDFC?"*
and *"Why is KABIL on HDFC's list?"* are the same assessment.

> **The rule:** `match_orgs` runs the same checks as `match_funders`, with the pair reversed.
> **Example:** if `match_funders(KABIL)` ranks HDFC as *passed*, then `match_orgs(HDFC)` lists
> KABIL as *passed*, with the identical check results.
> **Why it matters:** a pair judged differently depending on which side asked would be two
> matching engines. A property test asserts that the two directions agree for every pair.

`find_orgs(has=[...])` reads each credential through its evaluator. So `has: [12a]` returns orgs
where `has_identifier(12a)` is *met*, and reports *unknown* ones as a separate count, never as
absent.

**Decision 1: tools are complete, and skills do not chain them.**

> **The rule:** if a job needs a piece of data, the job's tool returns it. A skill never says
> "call X first".
> **Example:** *"Who can KABIL apply to?"* takes one call. `match_funders` already carries KABIL's
> gaps, so the answer does not need `get_org` → `match_funders` → `explain_match` (three calls).
> **Why it matters:** the model decides whether to load a skill, so a step written in a skill
> sometimes doesn't happen. A required step cannot live in optional text, for the same reason
> constraints stay in the prompt.

**Decision 2: there is one reader.** `get_org` and `get_funder` are rendered views of the
resolver's `EvidenceBundle`, which is the same object the evaluators read.
- This is what the removed `search_orgs` lacked. It had a query of its own and read only
  `registered_location_id`.
- A test enforces it: `agent/tools/match_tools.py` and `profile_tools.py` contain no SQL and import
  only `matching.service`.

**Decision 3: `find_funders` is stage 1 without an org.**
- *"Gives in Assam"* has one definition, and it lives in the `area` evaluator: footprints plus
  `funder_locations` plus stated pan-India, with *not recorded* counted separately.
- `find_funders` builds a stated profile, for example `{places: [Assam], themes: [livelihoods]}`,
  and runs the same fit query.
- It has no 50-row cap. It returns counts plus a page of results.

**Routing rule** (in `instructions.md`; it replaces rules 11–19):

| question | tool |
|---|---|
| a profile of one org or funder | `get_org` / `get_funder` |
| a list of funders or orgs by place, theme, type or credential | `find_funders` / `find_orgs` |
| a judgement about fit, eligibility or rank | `match_funders` / `match_orgs` / `explain_match` |
| any other fact | `db_query`, never to re-derive a profile field or a judgement |

The agent goes from 6 tools to 13. Each tool renders within an output budget, the way
`sql/render.py` does.

**Skills: presentation only, and each formats the output of one tool.**

| skill | formats the output of |
|---|---|
| `funder-shortlist-brief` | `match_funders` |
| `application-readiness` | the gaps from `explain_match` |
| `funder-comparison` | `explain_match` with more than one funder |
| `funder-profile-brief` | `get_funder` |
| `ngo-shortlist-brief` | `match_orgs` |

## 2. Matching service — `backend/app/matching/service.py`

Yes: both tools call one service, as does every other client (the CLI, evals, a future REST
endpoint). Three operations:

```python
async def shortlist(org_id: int, *, criteria: CriteriaRef = ACTIVE,
                    limit: int = 20, offset: int = 0) -> Shortlist: ...
async def assess(org_id: int, funder_id: int, *, criteria: CriteriaRef = ACTIVE) -> Assessment: ...
async def assess_many(org_id: int, funder_ids: list[int], *,
                      criteria: CriteriaRef = ACTIVE) -> list[Assessment]: ...
async def resolve(kind: Literal["org", "funder"], text: str) -> Resolved | Ambiguous: ...
async def profile(kind: Literal["org", "funder"], ref: int) -> OrgProfile | FunderProfile: ...
async def find_funders(*, places: list[str] = [], themes: list[str] = [],
                       funder_types: list[str] = [], limit: int = 20, offset: int = 0) -> FunderList: ...
async def shortlist_orgs(funder_id: int, *, criteria: CriteriaRef = ACTIVE,
                         limit: int = 20, offset: int = 0) -> OrgShortlist: ...
async def find_orgs(*, places: list[str] = [], themes: list[str] = [],
                    has: list[str] = [], limit: int = 20, offset: int = 0) -> OrgList: ...
```

`profile` renders the resolver's bundle and contains no query of its own. `find_funders` runs the
stage-1 fit query against a stated profile.

**Comparison and readiness stay compositions**, not operations:

- *Comparison* is `assess_many` with two or three ids. The skill lays the results side by side.
- *Readiness* is `assess(...).gaps`, an ordered list the service computes. Ordering is a business
  rule, so it lives in code: gate checks first, then weighted checks by weight (largest first), then advisory; within a role, `fail`
  before `unknown`; ties broken by the criteria file's `sort_order`. The skill only renders it.

A new operation is justified only when it needs data or logic the existing ones do not have.
`shortlist_orgs` is the reverse direction. It reuses the evaluators unchanged; only stage 1's
candidate query runs over orgs instead of funders.

`CriteriaRef` is `ACTIVE`, or a specific version id. Only the CLI and evals may pass a draft; the
agent's tools hard-code `ACTIVE`.

## 3. Criteria engine — representation

**Checks are leaves; groups combine them; roles say what a result does.**

```yaml
# backend/app/matching/criteria/funder_matching.yaml
set: funder-matching
version: 4                      # integer, bumped per PR
engine: 1                       # evaluator API this file needs; load refuses a mismatch

checks:
  - {code: area,     label: Gives where the NGO works, evaluator: shares_place,
     params: {levels: [district, state]}}
  - {code: theme,    label: Funds the NGO's theme,     evaluator: shares_theme}
  - {code: prog,     label: Runs a programme in that theme, evaluator: shares_programme_theme}
  - {code: reg_12a,  label: 12A registration,  evaluator: has_identifier, params: {id_type: 12a}}
  - {code: reg_80g,  label: 80G registration,  evaluator: has_identifier, params: {id_type: 80g}}
  - {code: csr_1,    label: CSR-1 registration, evaluator: has_identifier, params: {id_type: csr1}}
  - {code: audits,   label: 3 years of audits, evaluator: min_audited_years, params: {years: 3}}
  - {code: turnover, label: Meets the funder's turnover bar, evaluator: min_income,
     params: {threshold_from: funder_requirement}}
  - {code: board,    label: Board of 3 or more, evaluator: min_board, params: {count: 3}}
  - {code: cvs,      label: Team CVs on file, evaluator: has_document, params: {doc_type: team_cv}}
  - {code: projects_3, label: 3+ completed projects, evaluator: min_projects,
     params: {count: 3, fields: [funder, amount, theme, duration, results]}}

groups:
  fit:        {min_met: 1, of: [area, theme, prog]}
  statutory:  {all: [reg_12a, reg_80g, csr_1, audits]}

roles:                          # what each result does
  gate:     [fit, statutory, turnover]   # a fail removes; unknown marks "unverified"
  advisory: []                           # shown as a gap, carries no weight

applies:                        # which funders a check or group counts for
  statutory: {funder_type: [corporate_csr]}
  turnover:  {funder_requirement: turnover}   # only funders with a recorded turnover bar

weights:                        # ranks the funders that got in; totals 100, one table for all funders (v1)
  fit:        {weight: 40, checks: {area: 20, theme: 12, prog: 8}}
  compliance: {weight: 25, checks: {reg_12a: 8, reg_80g: 7, csr_1: 10}}
  financial:  {weight: 15, checks: {audits: 10, turnover: 5}}
  governance: {weight: 10, checks: {board: 6, cvs: 4}}
  programme:  {weight: 10, checks: {projects_3: 10}}

partial:                        # a met check may earn part of its weight
  area: {district: 1.0, state: 0.6, pan_india_stated: 0.3}

ranking: [gate_status, score_min, coverage, shared_districts, funder_id]
```

**Three-valued combinators** (Kleene logic), so there is no expression language:

| combinator | met when | fail when | otherwise |
|---|---|---|---|
| `all: [...]` | every member met | any member fail | unknown |
| `any: [...]` | any member met | every member fail | unknown |
| `min_met: n, of: [...]` | met ≥ n | met + unknown < n | unknown |

Groups may nest groups. That covers *"12A **and** 80G **and** (CSR-1 **or** registered before
2021)"* without a parser.

**Roles:**

| role | effect of `fail` | effect of `unknown` |
|---|---|---|
| `gate` | funder moves to *did not pass*, with the failing check named | `gate_status = unverified` — kept, flagged, ranked below `passed` |
| weighted (in `weights`) | earns 0 | earns 0 in `score_min`, its full weight in `score_max` |
| `advisory` | listed in `advisory_gaps` | listed in `advisory_gaps` |

**`applies` selectors are a closed vocabulary:** `funder_type`, `funder_requirement`, `always`.
A new selector is code, like a new evaluator.

A check can be both a gate and weighted. Take 12A for a CSR funder: the gate decides whether
the funder is in, and the weight separates *passed* from *unverified* funders by how much is known.

### Weights and the score

> **The rule:** weights only order the funders the gates let in. A weight never lets a funder in.
> **Example:** an HDFC programme that requires 12A gets nothing from KABIL's district match while
> KABIL's 12A is unknown. It stays *unverified*, and no score lifts it to *passed*.
> **Why it matters:** a legal requirement cannot be made up for with a good fit somewhere else.

**Unknown is not zero.** Each funder gets a range, not one number:

| KABIL × HDFC | weight | result |
|---|---|---|
| area (same district), theme | 32 | met → 32 |
| 12A, 80G | 15 | met → 15 |
| programme, CSR-1, audits, board, CVs, 3 projects | 48 | unknown |
| turnover | 5 | does not apply, because HDFC has no recorded bar → drops out |

```
score_min = met points / applicable weight     = 47 / 95 → 49
score_max = (met + unknown) / applicable weight = 95 / 95 → 100
coverage  = weight with evidence / applicable   = 47 / 95 → 49%
```

- **The ranking uses `score_min`**, the score the evidence supports. The answer shows both
  numbers: *"at least 49, up to 100 once KABIL's audits and CSR-1 are recorded"*.
- **The fix-first hint comes from the gap between the two.** The unknown check with the largest
  weight is the most valuable thing to research or upload next.
- **A check that does not apply drops out**, and scores are computed out of what applies, so a
  funder is never penalised for a bar it does not have.
- **Partial credit** comes from `partial`: sharing a district earns the full 20 for `area`,
  sharing only a state earns 12, and a funder that only states *pan-India* earns 6.
- **Every score carries its breakdown by category**:
  `fit 32/40 · compliance 15/25 (CSR-1 ?) · financial ?/10 · governance ?/10 · programme ?/10`.
- **One table for every funder in v1.** Tables per funder type can be added later through
  `applies`, without a redesign. They are deferred until labelled pairs exist for each type.
- **The weighted score is the only score.** The rubric scores in `fit_scores` are not used in any
  matching answer. Two scores for one pair would drift apart, which is the second-home problem.
  Whether the table and its `[score:N]` marker are removed is a separate decision.

The ranking key comes from a closed vocabulary and ends in `funder_id`, so ties are deterministic.

**The loader** (`app/matching/config.py`, Pydantic) refuses:
- an unknown evaluator, selector or ranking key;
- a param that fails the evaluator's own params model;
- a cycle in groups;
- a code used in two places;
- a `has_document` type missing from `document_types`;
- `engine` ≠ the code's evaluator API version;
- weights that do not total 100, or category weights that do not equal the sum of their checks;
- a weight on a check the file does not define, or a `partial` level the evaluator does not emit.

## 4. Evidence resolver — `backend/app/matching/evidence.py`

Yes, it is separate from evaluation. Evaluators stay pure (no pool, no async), the same discipline
as `agent/tools/sql/validator.py`, so each is unit-tested with hand-built evidence.

**Evaluators declare what they read:**

```python
@evaluator("has_identifier", reads={"org.identifiers", "org.credential_events", "org.research"},
           params=HasIdentifierParams)
def has_identifier(ev: EvidenceBundle, funder: FunderRef, p: HasIdentifierParams) -> CheckResult: ...
```

The engine takes the union of `reads` over every check that applies, and the resolver loads each
kind **once**: org kinds with one query each, funder kinds with one query for the whole candidate
set (`funder_id = ANY(%s)`). The query count depends on the evidence kinds in use, never on the
number of funders.

**Normalised record** — every source becomes the same shape:

```python
@dataclass(frozen=True)
class Evidence:
    kind: str                  # "org.identifiers", "org.financials", "org.documents", ...
    subject: str               # "org:126" / "funder:2"
    key: str                   # "12a", "FY2023-24", "team_cv"
    value: Any                 # id_value, total_income (rupees), board size
    status: EvidenceStatus     # see §5
    source: Literal["research", "vault", "seed"]
    document_id: int | None
    as_of: str | None
    valid_until: date | None
    cite: str                  # "[org:126]" or a document reference
```

| source table | evidence kind | normalisation |
|---|---|---|
| `org_identifiers` + `credential_events` | `org.identifiers` | latest event decides status; `valid_until` carried |
| `org_financials` | `org.financials` | one record per fiscal year; money in rupees, the unit rule |
| `documents` (Vault, `doc_type` from vocabulary) | `org.documents` | `source='vault'` → *on file* |
| `documents` (research archive) | `org.documents` | `source='research'` → *recorded* |
| `contacts` (`office_bearer`) | `org.board` | count + names |
| `grants`, org `programs` | `org.projects` | one record per project; `fields_present` for funder, amount, theme, duration, results |
| `entity_research.not_found` + `researched_at` | `org.research` | which concepts were searched and not found, and when |
| `funder_eligibility` (`requirement_code`, `params`) | `funder.requirements` | typed thresholds; unmapped wording kept as `unchecked` |
| locations, tags, programmes | `org.places`, `funder.places`, `*.themes`, `funder.programmes` | stage 1, one set-based query |

## 5. Evidence semantics — six states, three outcomes

The outcome stays **met / fail / unknown** — the ranking and gates need only three. A **basis**
says why, and carries the six distinctions:

| situation | outcome | basis | reads as |
|---|---|---|---|
| evidence exists and passes | met | `recorded` or `on_file` | "12A AAAT1234E ✓" |
| evidence exists and fails | **fail** | `recorded` or `on_file` | "board of 2, needs 3" |
| not researched / not recorded | unknown | `not_researched` | "not recorded" |
| researched, explicitly not found | unknown | `searched_not_found` (+ date) | "searched 2026-10-04, not found" |
| document recorded in research | met | `recorded` | "12A recorded; certificate not uploaded" |
| document available in the Vault | met | `on_file` | "12A certificate on file" |

> **The rule:** only positive evidence against the bar produces `fail`.
> **Example:** research searched MCA for KABIL's CSR-1 and found nothing →
> `unknown / searched_not_found`. A `credential_events` row with `event='cancelled'` → `fail`.
> **Why it matters:** "we could not find it" is a statement about our research, not about the NGO.

When a check needs a document (`requires: on_file`), `recorded` alone gives `unknown` with reason
`not_on_file`. The fundraiser's fix is then specific: upload the certificate.

## 6. Research agent boundary

| research agent (fuzzy) | deterministic writers and validators |
|---|---|
| finds pages, reads PDFs, extracts facts with quotes | validates vocabulary: `id_type`, `doc_type`, `requirement_code`, fiscal-year format |
| classifies themes; maps a funder's wording to a requirement code and params | validates params against the code's Pydantic model, e.g. `turnover: {min_rupees: int}` |
| records what it searched for and did not find (`not_found`) | enforces units (rupees, never crore), provenance columns, `is_inferred` |
| proposes; never decides eligibility | conflicts → held for review; unmapped wording → stored as free text and shown "not machine-checked" |

The path already exists: `save_research` → `promote_research` → `ingest/writer.py`. New work is
the requirement vocabulary and its validator. The vocabulary is read from the **active** criteria
set, so the research agent can only propose codes the engine can evaluate.

## 7. Structured outputs — `backend/app/matching/models.py`

```python
class CheckResult(BaseModel):
    code: str; label: str; group: str | None; role: Literal["gate", "weighted", "advisory"]; weight: int
    outcome: Literal["met", "fail", "unknown"]
    basis: Literal["recorded", "on_file", "not_researched", "searched_not_found", "not_on_file"]
    reason_code: str                 # "below_threshold", "expired", "count_short", ...
    reason_params: dict              # {"have": 1, "need": 3}
    evidence: list[EvidenceRef]      # cite strings + document ids

class Assessment(BaseModel):
    criteria_version: int; criteria_hash: str
    funder: FunderRef                # id, name, funder_type
    gate_status: Literal["passed", "unverified", "failed"]
    fit_checks: list[CheckResult]; eligibility_checks: list[CheckResult]
    score_min: int                   # 0–100, from met weight only; the ranking uses this
    score_max: int                   # 0–100, if every unknown were met
    coverage: int                    # % of the applicable weight backed by evidence
    breakdown: dict[str, CategoryScore]  # "fit" → CategoryScore(earned, unknown, applicable)
    gaps: list[CheckResult]          # ordered (§2)
    advisory_gaps: list[CheckResult]
    citations: list[str]

class Shortlist(BaseModel):
    criteria_version: int; criteria_hash: str; org: OrgRef
    ranked: list[Assessment]; did_not_pass: list[FunderRef]; not_enough_recorded: list[FunderRef]
    total_funders: int; offset: int; limit: int
```

`reason_code` and `reason_params` are data. The **tool layer** (`agent/tools/match_tools.py`)
renders them to compact cited text within an output budget, as `sql/render.py` does. Evals assert
on codes, not phrasing.

## 8. Versioning — `criteria_sets`

```
YAML in git ──make criteria-load──► draft ──make criteria-activate──► active ──► retired
                (validate, hash)     (CLI + evals only)   (one per set, in a txn)    (kept forever)
                                                               ▲
                                       rollback = criteria-activate VERSION=<retired one>
```

- Table (`db/migrations/0023_criteria_sets.sql`): `set_name`, `version`, `status` (`draft` /
  `active` / `retired`), `content jsonb`, `content_hash`, `git_sha`, `engine_api`, `loaded_at`,
  `activated_at`, `retired_at`, `activated_by`. A partial unique index allows one `active` row per
  `set_name`. Rows are never deleted.
- The engine reads **active**, never "newest". A loaded draft changes nothing until someone
  activates it.
- Every `Assessment` carries `criteria_version` + `criteria_hash`. **Reproducible logic:** re-run
  any past version by id. Data changes over time; the result records the newest `as_of` among the
  evidence it used, so a re-run can say what moved.
- `make match-diff FROM=<version> TO=<draft>` (evals plan, tier 2) is the review artefact for
  activation.
- `ENV=staging` loading and activation are deliberate steps, like `make migrate`.

## 9. Extensibility

| scale | stage 1 | stage 2 | output | needs |
|---|---|---|---|---|
| 42 → 200 | one set-based query, milliseconds | one query per evidence kind | top 20 + counts | nothing new |
| 2,000 | the same query; SQL returns only candidates with shared > 0 or unknown, plus counts for the rest; uses `funder_footprints_location_idx` | candidate set bounded by stage 1; still one query per kind | `limit`/`offset` on `Shortlist` | an index on `funder_tags(tag_id)`; a query-count test at 2,000 synthetic funders |
| beyond, or a listing UI | — | — | — | a `match_snapshots` cache keyed by (org, criteria version, data watermark), invalidated on writes; **not built now** |

**More funder types.** `funders.funder_type` is free text today. Make it a controlled vocabulary
(`corporate_csr`, `private_foundation`, `family_trust`, `government`, `international`, `other`) via
a migration and the writer. Each type then gets its own profile in YAML through `applies`:
- `international` → FCRA required;
- `corporate_csr` → the CSR Rules gate;
- `government` → Darpan required.

A new type is a vocabulary value plus YAML, with no code. An unrecognised type falls back to
`always` checks only and is flagged `funder_type_unknown`.

**More check kinds:** one evaluator function, its params model and its `reads`, plus unit tests
for the four properties (zero evidence → unknown; monotonic; params honoured; cites what it used).
The YAML can use it immediately.

## 10. Prompt and skills

Four layers, one job each.

| layer | job | example |
|---|---|---|
| criteria YAML | *what* counts | `audited_3y: years: 3` |
| tools | *compute* it, the same way every time | `match_funders("KABIL")` → the ranked list |
| `instructions.md` | what the agent must **always** do | "never report unknown as not met" |
| skills | *how to present* a result for one job, loaded only when relevant | "turn KABIL's gaps for HDFC into an application checklist" |

> **The rule:** procedures become skills; constraints stay in the prompt (`docs/SKILLS.md`).
> **Example:** "unknown is *not recorded*, never *not eligible*" is in `instructions.md`, because
> a skill the model chose not to load would drop it. The ordering of a readiness checklist —
> statutory gaps first — is in a skill, because only a readiness question needs it.
> **Why it matters:** a skill is loaded at the model's discretion, so anything that must hold
> on every answer cannot live only there.

**`instructions.md`** — rules 11–19 become about six lines:

1. Route by the §1b table: profiles to `get_org` / `get_funder`, lists to `find_funders` /
   `find_orgs`, judgements to `match_funders` / `match_orgs` / `explain_match`. Never rebuild a
   profile field or the funnel in `db_query`.
2. Repeat each state as the tool gives it. Unknown is *not recorded*, never *not eligible*.
3. Name the funders in the *not enough recorded* block; they are not the bottom of the list.
4. State the criteria version the tool reports.
5. Cite `[funder:N]` and `[org:N]` as the tool returns them.
6. Offer `explain_match` as the next step; do not run it unasked.

**Skills — five, all Ask Sangam's**, each formatting one tool's output (§1b; they never chain tools), in `backend/app/agent/skills/<name>/SKILL.md`:

| skill | loaded when | what it adds | reads |
|---|---|---|---|
| `funder-shortlist-brief` | *"Which funders fit KABIL?"* | the write-up for a fundraiser: lead with the top few and why each fits, then the research that would let the unknowns be ranked | `match_funders` |
| `application-readiness` | *"What does KABIL need for HDFC?"* | turns `explain_match` gaps into an ordered to-do list — statutory gaps first, then funder bars, then readiness: *upload ITR-7 for FY2022-23 · renew 80G · add two board members* | `explain_match` |
| `funder-comparison` | *"Compare HDFC and SBI Foundation for KABIL"* | two or three funders' checks side by side, with the differences put first | `explain_match` with 2–3 funders |
| `funder-profile-brief` | *"Tell me about HDFC"* | where it gives, what it funds, what it requires, and what is not recorded | `get_funder` |
| `ngo-shortlist-brief` | *"Which NGOs fit HDFC Parivartan?"* | the funder-side write-up: top NGOs, why each fits, the credentials still unverified | `match_orgs` |

Sangam Import already has `funder-scan-for-fundraisers` and `ngo-brief-for-funders`. They are
written for research output, so the Ask skills borrow their structure but read from the tools.
Import's skills stay where they are.

**The mechanism is Import's, copied.** Ask Sangam has `read_file` today, but bound to virtual
state (`agent/build.py:44`), so it can reach no skill. Import shows the shape:

- a `/skills/` route to real disk inside a composite backend (`ingest/agent.py:77-87`);
- `skills=[SKILLS_ROUTE]` passed to `create_deep_agent` (`ingest/agent.py:207`).

Ask Sangam keeps `read_file` and gains `ls` only if the skills middleware needs it to list the
folder. Nothing that writes may reach `/skills/`: an `edit_file` there would rewrite a skill on
disk.


No skill holds a threshold or a number from the criteria file: the tools return each check's
label and parameters, and a skill only arranges them.

## Milestones (one PR each)

| | ships | gate |
|---|---|---|
| M1 | `matching/` package: models, evidence resolver, criteria loader + `criteria_sets` lifecycle, stage-1 evaluators, `program_tags` backfill, CLI | `make criteria-load && make criteria-activate && make match ORG=kabil` |
| M2 | stage-2 evaluators, combinators, roles, `applies`, weights + `partial`, score range and breakdown, ranking key, gaps ordering | unit tests: three-valued truth tables; zero rows → unknown; a funder with nothing recorded scores 0–100, never 0 |
| M3 | funder-side tools (`match_funders`, `explain_match`, `get_org`, `get_funder`, `find_funders`) over the service; prompt routing rule replaces rules 11–19; tool pins 6 → 11; a no-SQL-in-tool-modules test | one tool call per job in the trace; canary evals |
| M3c | org-side tools (`match_orgs`, `find_orgs`); `shortlist_orgs`, `find_orgs` in the service; tool pins 11 → 13 | a both-directions-agree property test; `find_orgs(has=[12a])` reports *unknown* separately |
| M3b | Ask Sangam skills (shortlist brief, readiness, comparison) + `/skills/` mechanism | skill read in the trace; no write tool |
| M4 | Vault `doc_type` vocabulary + fiscal year; `on_file` basis | an uploaded certificate flips `recorded` → `on_file` |
| M5 | `funder_eligibility.requirement_code/params`; research proposes, writer validates against the active vocabulary | HDFC's recorded bar drives `turnover` |
| M6 | `funder_type` vocabulary + type profiles | an `international` funder gates on FCRA |

Evals: `docs/features/2026-10-06-funder-matching-evals.md`, tiers E1–E6 alongside these.

#### M3b — Ask Sangam skills

- `backend/app/agent/skills/{funder-shortlist-brief,application-readiness,funder-comparison,funder-profile-brief,ngo-shortlist-brief}/SKILL.md`.
  Frontmatter is the advertisement, the body is the procedure (`docs/SKILLS.md`). Each body names
  the tool it reads, and none restates a constraint as if it lived only there.
- `agent/build.py`: a composite backend routing `/skills/` to that folder, plus
  `skills=[SKILLS_ROUTE]`. Mirror `ingest/agent.py:77-87, 207`; reuse its route class rather
  than copying it, if it lifts out cleanly.
- `instructions.md` gets one line: skills exist for writing up shortlists, readiness and
  comparisons. The six constraints above stay in the prompt.
- Tests, mirroring Import's:
  - every skill's frontmatter parses, and its `name` matches its folder;
  - **a tool is never reachable only through a skill** — Ask's twin of
    `test_a_tool_is_never_reachable_only_through_a_skill`;
  - the tool set is still the thirteen tools plus `read_file` (and `ls` if needed) — no write tool
    appears (`test_harness.py:106`);
  - `read_file("/skills/application-readiness/SKILL.md")` returns the file.
- Update `docs/SKILLS.md` (it describes Import's skills only) and `CLAUDE.md`'s skills paragraph.
- Evals: *"What does KABIL need for HDFC?"* returns an ordered list, statutory items first, and
  its trace shows the skill was read.

## Critical files

- New: `backend/app/matching/{service,engine,evidence,evaluators,config,models,__main__}.py`,
  `backend/app/matching/criteria/funder_matching.yaml`, `backend/app/agent/tools/match_tools.py`,
  `backend/app/agent/tools/profile_tools.py`,
  `db/migrations/0023_criteria_sets.sql`.
- Changed: `backend/app/agent/build.py` (TOOLS), `backend/app/agent/instructions.md` (routing rule
  replaces 11–19), `backend/app/ingest/writer.py` (programme themes, requirement codes),
  `frontend/features/ask/lib/toolLabels.ts`, `backend/tests/test_harness.py:106`,
  `backend/tests/test_prompt.py`, `Makefile`, `CLAUDE.md` (layout, the tool count).
- Reused: `ingest/taxonomy.clause_for` (programme themes); `0022` `maps_to`;
  `agent/tools/sql/render.py` patterns; the tool error-string convention
  (`agent/tools/graph_tools.py`); `entity_research.not_found` (`0016`); `credential_events` (`0006`).

## Verification

```bash
cd backend
pytest tests/test_matching_*.py -m "not integration"   # evaluators, combinators, loader, service
pytest -m integration tests/matching                    # fixture DB, golden pairs, query count at 2,000 funders
make criteria-load FILE=... && make match-diff FROM=<active> TO=<draft>
make criteria-activate VERSION=<draft> && make match ORG=kabil
make criteria-activate VERSION=<previous>               # rollback restores the earlier output
make up && make evals TAG=canary                        # COSTS MONEY
```
