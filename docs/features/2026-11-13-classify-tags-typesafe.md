# Taxonomy tags from TypeSafe Jev, not the researcher (#315, tags only)

Status: **Draft v1**, 2026-11-13. Issue: #315 (epic #335). No earlier plan covers this; `2026-10-07-taxonomy-in-tags.md`
is the tag tree itself and stays live.

## 1. Goal

**When a funder or NGO is saved from Import, a small classifier picks its taxonomy tags from the researcher's evidence,
and each tag carries a probability.**

Success, measured on one funder pulled locally (§7, M1 gate):
- every tag Jev writes is one a person reading the `tag_note` would accept;
- it misses nothing the researcher's Sonnet codes got right;
- the probability says how sure, so a later threshold can be tuned from data.

Out of scope: news classification, Pitch grading, story grouping, `rfp_tags`. Each gets its own issue if this works.

## 2. Blast radius

Built by hand from `ask/tools/sql/catalog.py`, `CLAUDE.md` and `db/migrations/` (there is no domain map).

| surface | hop | why affected | status | notes |
|---|---|---|---|---|
| `org_tags`, `program_tags`, `funder_tags` | 0 | Jev's codes written here, `tagged_by='typesafe-jev'`, new `confidence` | in scope | insert-only, a staff tag still wins |
| `save.py::save_to_catalog` | 1 | the one place a real save runs; classify happens before its transaction | in scope | — |
| `write_tags` / `write_funder_tag` | 1 | carry `tagged_by` and `confidence` from the record | in scope | — |
| researcher contract (`finding_types.py`), research skills | 1 | still emit codes, used as the fallback | unchanged in M1 | M2 drops them |
| Ask's SQL catalog | 1 | lists `tagged_by`; a new value is harmless | unchanged | `confidence` left out of the catalog (a security decision, later) |
| `0043_tag_writes_logged` trigger | 1 | logs `org_tags`/`program_tags` rows for undo | unchanged | generic trigger, a new column rides along |
| Preview paths (`write_preview`, `review_view`, `Gate(plan=True)`) | 1 | do not classify, so they show researcher codes | accepted | Scout's review card shows no tag codes (grep of `frontend/features/ingest`) |
| Registry / profile pages | 2 | read tags, not `tagged_by` or `note` | unaffected | — |
| `rfp_tags` (`calls/pull.py`, `writer_funder.py:531`), keyword Schedule VII table | 1 | other tag writers | out of scope | — |
| News, Pitch grade, group | — | other classifiers in #315 | out of scope | separate issues |

## 3. High-level design (HLD)

```
BEFORE                                            AFTER (★ new)
entity-researcher (Sonnet)                        entity-researcher (Sonnet)            unchanged
  save_research: evidence + tag_note + codes        save_research: evidence + tag_note + codes
        │                                                 │
promote_research → save_to_catalog                promote_research → save_to_catalog
        │                                           ★ classify_tags(row)   ── no DB connection held
        │                                           │   per public, tagged finding → Jev, 1 HTTP call
        │                                           │   answer → replace codes, attach confidence
        │                                           │   None (off / error) → keep researcher codes
  BEGIN … promote() → write_tags … COMMIT          BEGIN … promote() → write_tags(+tagged_by, confidence) … COMMIT
```

No agent, subagent, tool or prompt changes. The supervisor still calls `promote_research`.

**One request per finding, two shapes of question.** `choice` returns one answer and a distribution that sums to 1,
so it cannot say "both education and health". The design leans on that:

| field | list size | Jev question | what `confidence` stores |
|---|---|---|---|
| theme | 18 | one `noul` per theme: "is this work about X?" | the noul (0–1, independent) |
| sub-theme | 66 | one `choice` per theme over its sub-themes plus `none` | the choice's probability |
| population | 15 | one `noul` each | the noul |
| lens | 4 | one `noul` each | the noul |

That is 55 questions in one request. The `state` is
`{"organisation": name, "evidence": tag_note + the finding's own description}`.

> **The rule:** a theme is written when its noul is ≥ 0.5, at most three (`MAX_THEMES`), highest first. Its sub-theme is
> written instead when that theme's choice puts ≥ 0.5 on one sub-theme. Populations and lenses: noul ≥ 0.5.
> **Example:** Azim Premji Foundation's evidence reads "teacher education in government schools across Karnataka".
> Jev says `school-quality 0.94`, `primary-community 0.06`. The sub-theme choice says `teacher-leadership 0.81`, so
> `teacher-leadership` is written with `confidence 0.81`. `primary-community` is not written.
> **Why it matters:** one HTTP call per finding, and nothing invented, because every answer comes from our tree.

> **The rule:** a finding whose `source_url` is private (`is_private_source`, the `sangam.invalid` domain: Doc Vault and
> staff spreadsheets) is never sent. It keeps the researcher's codes.
> **Example:** a CSO's FCRA letter in their Doc Vault tags `children`. That text stays in Sangam.
> **Why it matters:** TypeSafe's retention and training terms are not agreed yet.

The trade-off: classifying in `save_to_catalog`, not inside `promote()` or `write_tags`. The pool is shared with the
checkpointer (max 10). An HTTP call inside the save transaction would hold a connection for ~1 s per finding.

## 4. Low-level design (LLD)

**Settings** (`backend/app/core/config.py`): `typesafe_api_key: str = ""`, `classify_model: str = "off"`. A deploy
gets `off` until someone turns it on. Add both to `.env.example`.

**Client** (`backend/app/integrations/typesafe.py`, ~60 lines): one async function,
`ask(state: dict, questions: dict) -> dict | None`.
- Plain `httpx.AsyncClient`: `POST https://api.typesafe.ai/v1/systemone` with
  `Authorization: Bearer <key>` and body `{state, model, questions}`. The response is `{answers: {id: {...}}, usage}`.
- `langchain-typesafe` (PyPI 0.1.0) was considered. It pulls in `httpx2` and pins `langchain-core>=1.8`, which is
  too much for one POST.
- It never raises: `None` on off, no key, timeout (10 s) or a non-200. It logs `usage` tokens once per call.
- The URL is ours, not model-supplied, so `guarded_client` is not needed. TLS is verified as usual.

**Classify step** (`backend/app/ingest/catalog/classify_tags.py`):
- `async def classify_tags(row) -> row`: for each finding with a `Tagged` concept (`identity`, `org_identity`,
  `program`) and a public `source_url`, build the 55 questions from `taxonomy.VOCABULARY`. Call the client, with up to 4
  findings at once.
- `def pick(answers) -> (themes, populations, lenses, confidence)`: pure, applies §3's thresholds. Most of the tests
  live here.
- On an answer, it returns a copy of the finding with the codes replaced, plus `tag_confidence: {code: p}` and
  `tagged_by: "typesafe-jev"`. If the finding had no `tag_note`, it sets one from the evidence's first 200 characters,
  because `Tagged` refuses tags without one.
- The research row in `entity_research` is never rewritten. It still holds what the researcher said, which the M1
  gate compares against.

**Wiring:**
- `save.py::save_to_catalog` (`backend/app/ingest/catalog/save.py:284`): `row = await classify_tags(row)` inside
  `for row in rows:`, before `pool.connection()`.
- `promote_records.py::_tags` (`:367`) passes `tag_confidence` and `tagged_by` through.
- `rows.py` (`:164`): the record gets `tag_confidence: dict[str, float] = {}` and `tagged_by: str | None = None`.
- `writer.py::write_tags` (`:439`) writes `rec.tagged_by or EXTRACTOR_TAGGER` and `rec.tag_confidence.get(code)`. The
  programme roll-up (`promote_documents.py:331`) uses the same record, so it gets the same values.

**Migration** (`db/migrations/0058_tag_confidence.sql`): `ALTER TABLE org_tags, program_tags, funder_tags ADD COLUMN
confidence real CHECK (confidence BETWEEN 0 AND 1)`. NULL means a person or the researcher set it.
`verify_against_db` only refuses a catalogued column that is missing (`catalog.py:1098`), so an uncatalogued new
column boots fine.

**Docs:**
- `CLAUDE.md`'s model tiers gain a `CLASSIFY_MODEL` line (off by default).
- `docs/ARCHITECTURE.md` §4 gets the private-source rule.
- One CHANGELOG line.
- `make wiki-update` is offered, not run.

## 5. Security review

- **No new endpoint and no new catalog table.** `confidence` stays out of Ask's catalog.
- **Egress:** one fixed host. It sends public evidence text only: private-source findings are filtered before the call
  (`is_private_source`). There are no names of people beyond what public pages print.
- **Secrets:** `TYPESAFE_API_KEY` comes from the environment, and staging or production get it as a Vercel env var.
  The key never reaches a log.
- **Default off.** Turning it on in staging waits on TypeSafe's retention and training terms (§8).
- **Input:** answers are mapped only onto codes in `taxonomy.VOCABULARY`. An unknown key in a response is ignored, so
  a bad response cannot write a tag that isn't in the tree.

## 6. Testing

Unit tests, no database and no network:
- `tests/test_classify_tags.py`:
  - `pick()` thresholds: two themes both ≥ 0.5, so both are written; a fourth theme is cut by `MAX_THEMES`; a
    sub-theme below 0.5 falls back to its theme; every noul < 0.5 writes nothing and keeps nothing either.
  - A private-source finding is not sent.
  - The client returning `None` keeps the researcher's codes and `tagged_by`.
  - A tagged finding with no `tag_note` gets one.
- `tests/test_typesafe.py`: with `httpx.MockTransport`, a 200 parses; a 401, a 500, a timeout and `classify_model=off`
  each give `None`; the key is not in the log output.
- `writer.write_tags`: `tagged_by` and `confidence` reach the INSERT (monkeypatched `conn`).
- `tests/test_migration_integrity.py` (integration) picks up 0058.

Zero means unrecorded: a finding with no tags after classify means "Jev found nothing ≥ 0.5", not "no themes". The
report says so in its line for that finding.

## 7. Milestones

#### Milestone 1: Jev picks tags at save, off by default (one PR)
- **Deliverable:** with `CLASSIFY_MODEL=jev-latest` and a key, saving an Import writes Jev's tags with a probability.
  With it off, nothing changes.
- **Touches:** backend, db.
- **Key tasks:**
  - [ ] Settings and `.env.example`.
  - [ ] `integrations/typesafe.py`.
  - [ ] `catalog/classify_tags.py`.
  - [ ] Wiring in `save.py`, `promote_records.py`, `rows.py`, `writer.py`.
  - [ ] `0058_tag_confidence.sql`.
  - [ ] Tests.
  - [ ] CLAUDE.md, ARCHITECTURE.md, CHANGELOG.
- **Acceptance criteria:**
  - `cd backend && pytest tests/test_classify_tags.py tests/test_typesafe.py && ruff check .`
  - **The one-funder gate**, on the local database:
    1. `make migrate`. Set `CLASSIFY_MODEL=jev-latest` and `TYPESAFE_API_KEY` in `.env` (the user does this) and
       `make up`.
    2. In Scout as staff, research one funder from public sources only. Pick one with a mixed portfolio, so
       multi-theme picking gets exercised.
    3. Before saving, delete that funder's `is_inferred` rows in `funder_tags`. `write_tags` is
       `ON CONFLICT DO NOTHING`, so old rows would hide the result.
    4. Save (`promote_research`). One SELECT then lists, per tag: `code, tagged_by, confidence, note`. Beside it goes
       the researcher's codes, read from the funder's `entity_research.findings`.
    5. A person reads both lists against the `tag_note`s and records the result in the PR body: kept, added, lost.

#### Milestone 2: the researcher stops choosing codes (decided after M1's gate)
- **Deliverable:** researchers save evidence only. Every tag comes from Jev. There's a `TAG=classify` eval.
- **Touches:** backend, prompt and skills.
- **Key tasks:**
  - [ ] `Tagged` codes become optional, then removed from the hint list.
  - [ ] The two research skills edited.
  - [ ] An eval against `tagged_by='staff'` rows, comparing precision and recall per field with Sonnet's codes.
- **Acceptance criteria:** the eval shows Jev ≥ Sonnet on both fields, and `make evals TAG=classify` passes.

## 8. Open questions and risks

- **Data terms:** TypeSafe's retention and training policy is unknown. M1 sends public text only and stays off on
  staging until the terms are agreed.
- **Pricing:** $0.04 / 1M input tokens comes from a third-party listing. A finding is ~3k tokens with 55 questions, so
  a funder with 10 tagged findings costs about $0.001. The gate's logged `usage` confirms it.
- **55 questions in one request:** whether the API caps questions per request is undocumented. If it does, split the
  request by field (three calls).
- **Thresholds of 0.5** are a guess. The gate's probabilities are the first data for tuning them.
- **Preview vs save:** the plan preview shows researcher codes and the save writes Jev's. This is accepted for M1
  because no screen shows tag codes before saving.
