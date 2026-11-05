# Import: a researcher's save is fixed when it can be, and refused once when it can't

Part of [#171](https://github.com/project-tech4dev/sangam/issues/171) (epic #332), part 2. Branch
`fix/171-fixable-save-refusals`, stacked on #364. Part 1 (the stream heartbeat) is a separate PR off
`master`; part 3 is a decision below. Builds on `2026-10-11-import-save-errors.md`, which made every refusal short
and specific; that document is still live, and nothing here undoes it.

## 1. Goal

**A researcher who has done the reading gets its research saved, instead of re-sending 45 KB for a mistake the
save could have fixed, or learning about its problems one refusal at a time.**

Success: the refusals in the table below either save or come back once, listing every problem.

The Rohini Nilekani run of 2026-11-04 (thread `import-75055e6a…`) shows the cost. The researcher read for 9 minutes,
then needed four saves:

| Try | Refused for | After this plan |
|---|---|---|
| 1 | `findings` sent as a 45 KB string, not valid JSON (`Extra data at character 45048`) | still refused (see "Fixes 1–2" below) |
| 2 | `summary` missing; a `metric` gap carrying `fiscal_year` | the year is cleared; `summary` refused **together with** try 3's problems |
| 3 | `identity.populations`, `identity.lenses`, `csr_spend FY2024-25`: no finding and no gap | already listed in try 2 |
| 4 | saved, 07:24 | try 3 saves |

Each retry on Opus took about 2 minutes, and by then the screen had already dropped the stream.

## 2. Blast radius

Built by hand from `CLAUDE.md`, `research_records.py` and the save path; there is no domain map in this repo.

| Surface | Hop | Why affected | Status |
|---|---|---|---|
| `research_records.py`: `Gap`, `ContactFinding`, `EntityResearch` | 0 | three validators get more forgiving | in scope |
| `middleware.py`: `parse_payload`, `refusal_text`, `SaveRefusal` | 0 | string repairs and the combined refusal | in scope |
| `contract.py`: `unanswered` | 1 | called from the refusal as well as the tool; unchanged | in scope (reused) |
| `prompts/entity_researcher.md` | 1 | the staff-only gap rule invents a concept (fix 4) | in scope |
| `save_vault_findings` (`VaultResearch`) | 1 | shares `SaveRefusal` and `Gap` | in scope for fixes 1–3, 5; the contract does not apply to it |
| Stored `entity_research.findings` | 1 | the brief re-validates old findings | safe: every change accepts more, none refuses more |
| Brief, promote, writer, tables, migrations | 2 | read the saved object, whose shape is unchanged | not affected |
| SQL catalog, Ask Sangam | 2 | no table or column changes | not affected |
| Frontend | 2 | the Import screen shows refusals as text | not affected |
| `EscalateAfterFailedSave` / `save_failed` | 1 | keys on the `Error invoking tool` prefix | kept: refusals keep the prefix and `status="error"` |

## 3. High-level design

```
researcher ── save_research(findings) ──► ToolNode ─► SaveRefusal ─► save_research body ─► upsert
                                            │            │                  │
                       schema (Pydantic) ───┘            │                  └─ contract.unanswered
                       NEW  Gap drops a year on a        │                     (refuses with REFUSED: …)
                            non-yearly concept (fix 5)   │
                       NEW  EntityResearch drops summary │
                            keys (fix 3)                 │
                       NEW  office words skip the        │
                            surname check (fix 6)        │
                                                         ├─ NEW  repairs a string payload: missing closers,
                                                         │       "https":"// (fixes 1–2)
                                                         └─ NEW  on a schema refusal, also lists the
                                                                 contract's problems (fix 7)
```

The key trade-off is **repair or refuse**. A repair is right only when the intent is certain and nothing is lost:
- a year on a `metric` gap means nothing, so dropping it loses nothing;
- `fact_count` belongs to the summary the parent builds.

It is wrong when it would invent data:
- a cut-off payload with closers added would save half the findings as if they were all.

Strict `extra="forbid"` stays everywhere else, because refusing an unknown key is what catches `type` written for
`doc_type` (see the 2026-10-11 plan).

No database, Storage, Neo4j or model change. The only new model call is none: the contract check is code.

## 4. Low-level design

### Fixes 1–2: a string payload (`middleware.py::parse_payload`)

> **The rule:** repair a string only where a closer or a quote was dropped, never where content was.
> **Example:** a researcher's 9.6 KB save ends `"basis":"inferred"}]` (the final `}` is missing). Appending one `}`
> parses, and the save goes through. A save cut off mid-finding (`… "evidence": "The Foundat`) is still refused.
> **Why it matters:** a payload cut after finding 80 of 130 must not save as 80 findings that look complete.

- **Fix 1.** After the strict parse fails, append at most two closers, chosen from a bracket stack of the text
  (outside strings), and parse again. Accept only when the text ends outside a string and right after a complete
  value: a `}`, `]` or a closing quote (not a number, which may itself be cut).
  - The parsed object then goes through the schema **and** the contract as usual. A payload truncated before its
    `gaps` fails `unanswered` and is refused.
- **Fix 2.** When the strict parse fails, replace `"https":"//` and `"http":"//` (with any spacing) with
  `"https://` / `"http://` and parse again.
  - This is never valid as an intended key pair; it was seen in two runs in a row (IRCTC, 43 KB).
- Today's 45 KB case (`Extra data` after the object) stays refused. That text is junk *after* a complete object.
  `parse_payload` already forgives a surplus closer, and anything else is not ours to guess.
- `test_parse_payload_never_guesses` changes: `'{"a": {"b": 1}'` now parses, while `'{"a": 1'` and `'{"a": '` still do not.

### Fix 3: summary keys in the save (`research_records.py::EntityResearch`)

- `EntityResearch`'s existing `_drop_null_extras` step also drops the keys only `ResearchSummary` has (`slug`,
  `fact_count`, `source_count`, `concepts_found`, `not_found`, `saved`), derived from the two models' fields.
- Every fix in this plan changes a function that already exists; none adds a check.
- Any other unknown key is still refused.
- Example: `{"entity_name": "IRCTC", "fact_count": 0, …}` saves; `{"entity_name": "IRCTC", "factcount": 0}` is
  refused as today.

### Fix 4: the staff-only gap invents a concept (`prompts/entity_researcher.md:22`)

- Today: "record any staff-only fact as a `blocked` gap", so the model wrote `{"concept": "staff_dataset"}`.
- New: "record each staff-only fact as a `blocked` gap **under the concept it belongs to**, e.g. `csr_spend` for a
  filing's spend, never a concept of its own".
- The refusal for an unknown concept already lists the allowed ones; that stays.

### Fix 5: a year on a gap that is not by year (`research_records.py::Gap`)

- `_year_only_when_yearly` today raises `'metric' is not by year; leave fiscal_year empty` (line 845).
- New: the same validator moves the year into `detail` and clears `fiscal_year`.
  - `{"concept": "metric", "fiscal_year": "FY2025-26", "detail": "No reach figures found."}` saves as
    `detail: "No reach figures found. (FY2025-26)"`.
  - Nothing is lost.
- A malformed year on a yearly concept (`"2025"` on `csr_spend`) is still refused.

### Fix 6: an office's mailbox read as a person's (`research_records.py::ContactFinding`, line 572)

- In the existing `_only_shared_mailboxes`, skip the surname check when the name's last word is an office word: `secretariat`, `office`, `desk`, `cell`, `team`,
  `department`, `division`, `committee`, `foundation`, `trust`, `helpdesk`, `csr`.
- Example: "ONGC Company Secretariat" with `secretariat@ongc.co.in` saves.
- "Rahul Sharma" with `rsharma@…` is still refused.
- The shared-mailbox attestation (`is_role_mailbox`) is unchanged.

### Fix 7: one refusal lists the schema's and the contract's problems (`middleware.py::refusal_text`)

> **The rule:** when the schema refuses a save, the refusal also lists what the contract would refuse.
> **Example:** Rohini's try 2 would have read: `summary: Field required`, then
> `identity.populations: no value and no gap`, `identity.lenses: no value and no gap`,
> `csr_spend FY2024-25: no finding and no gap`. One retry instead of two.
> **Why it matters:** each retry re-sends the whole payload, about 2 minutes on Opus.

- Validate the findings and the gaps **one by one** (the `Finding` union and `Gap`).
- Build `EntityResearch.model_construct(...)` from the ones that pass and run `contract.unanswered` on it.
- **Drop a contract line for any concept that had a finding or gap fail validation.** Otherwise a broken
  `csr_spend` finding would be reported as "csr_spend: no finding". That concept's schema line already covers it.
- Append the remaining lines under `Also, the save needs:` within the existing `REFUSAL_LINES` cap. The message keeps
  its `Error invoking tool` prefix, so `save_failed` and the escalation still see a failed save.
- `save_research` only: `VaultResearch` has no contract.
- If any of this raises, the refusal is today's (the existing `try/except` in `_short` already does this).

## 5. Security review

- No new endpoint, table, catalog entry, credential or PII.
- Fix 6 loosens a check that keeps personal email addresses out of Sangam. The office-word list is closed and
  named in code. A person's name never ends in one of those words, and `is_role_mailbox` must still be attested.
- Fixes 1–2 parse model-written text; the result goes through the same strict schema as any other payload.
- Fix 7 runs pure code over the payload already in memory; no I/O.

## 6. Testing

All unit-tier, in `tests/test_save_research_payloads.py`: its `ToolNode` + `SaveRefusal` harness runs the real
schema with no database. Each fix gets the example from the issue:

| Fix | Test |
|---|---|
| 1 | a payload missing its final `}` saves; one missing `]}` saves; one cut mid-string is refused; one cut after finding 3 of 5 with no `gaps` is refused by the contract |
| 2 | `"source_url": "https": "//…"` saves with the URL rejoined (replaces today's `test_a_broken_string…`, which asserts the refusal) |
| 3 | `fact_count: 0` at the top level saves; `factcount` is still refused |
| 4 | the prompt names "under the concept it belongs to" (prompt-phrase test, like the existing ones) |
| 5 | a `metric` gap with `FY2025-26` saves with the year in `detail`; `csr_spend` with `"2025"` is still refused |
| 6 | "ONGC Company Secretariat" / `secretariat@ongc.co.in` saves; "Rahul Sharma" / `rsharma@x.org` is still refused |
| 7 | a missing `summary` plus a missing identity field gives one refusal with both lines; a broken `csr_spend` finding gives no "csr_spend: no finding" line; the refusal keeps its prefix |

Plus `pytest`, `ruff check .` and the integration tier as CI runs them. No eval: the change is deterministic. An
optional `make evals TAG=import` (~15 min, costs money) is not needed to merge.

## 7. Milestones

#### Milestone 1: repairs (fixes 1–6)
- **Deliverable:** the six refusals in #171's table save, except a truncated payload.
- **Touches:** backend, prompt.
- **Key tasks:** [ ] fix 1 and 2 in `parse_payload` [ ] fix 3 and 5 as `mode="before"` validators [ ] fix 6 office
  words [ ] fix 4 prompt line [ ] tests per fix [ ] CHANGELOG line, ARCHITECTURE §4 bullet "repair only where
  nothing is lost"
- **Acceptance:** `cd backend && pytest tests/test_save_research_payloads.py tests/test_ingest.py && ruff check .`

#### Milestone 2: one refusal for everything (fix 7)
- **Deliverable:** a schema refusal also lists the contract's problems.
- **Touches:** backend.
- **Key tasks:** [ ] per-item validation and `model_construct` [ ] drop lines for concepts that failed [ ] tests
- **Acceptance:** `cd backend && pytest tests/test_save_research_payloads.py tests/test_cov_ingest_contract.py`

Both go in one PR, one commit each. They touch the same two files, and a stacked PR for fix 7 alone would be
hard to review apart from fixes 1–6.

## 8. Open questions and risks

1. **Part 3: should a researcher keep running after the browser disconnects?** Recommended: yes, and stop only on
   an explicit Stop. On 2026-11-04 the disconnected run finished and saved Rohini's research. Stopping would have
   lost it. Decided in the heartbeat PR, not here.
2. **Fix 1's truncation risk.** Pinned by the "cut after finding 3 of 5" test. If it still looks too risky, fix 1
   can be dropped without affecting the rest.
3. **Fix 7 and the cap.** `REFUSAL_LINES` already caps the list. A save with 15 schema errors may show no contract
   lines, which is acceptable: the next try gets them.
