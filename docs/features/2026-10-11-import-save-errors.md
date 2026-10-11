# Import: refused saves say exactly what to fix, and previews write nothing

## Context

The Rohini Nilekani run (trace `de868c54…`) finished, but two steps failed:

- **A refused save that hid its own reason.** `save_research` was refused for 3 schema errors.
  - LangChain's ToolNode error starts with the whole 130-finding payload (`Error invoking tool 'save_research' with kwargs {…} with error: …`).
  - The message was moved to `/large_tool_results/…`, the read-back was truncated, and the researcher lost ~4 min.
- **A preview that wrote to the database.** `compare_with_catalog` hit `UniqueViolation (state, Mizoram, 1)`.
  - Its "dry run" (`Gate(plan=True)`) still calls `geography._ensure`, which SELECTs and then INSERTs `locations` rows with no ON CONFLICT, on an autocommit connection.
  - Locally Mizoram (id 107), Rajasthan and Kerala were all created by previews.

Across the last 21 Import traces, `save_research` was refused **10 times**, and each one traces back to the prompt disagreeing with the schema:

| n | Error | Why the model did it |
|---|---|---|
| 6 | `org_identifier`: "status 'registered' needs the registration's number, unless it is 'claimed'" | The prompt never states this rule |
| 2 | `document.notes`: extra_forbidden | 9 concepts have `notes` and document does not. The prompt even asks for `fetched_at` on documents, which also doesn't exist |
| 1 | `partner`: "source_type and evidence_tier come together" | "Both or neither" is stated only for org runs. `research_goals` never lists either field |
| 1 | `findings.replace`: extra_forbidden | `replace` was put inside `findings` instead of beside it |

**Goal:**
- every refusal comes back short and names the exact fix;
- the prompts stop asking for fields that don't exist;
- a preview never writes;
- a find-or-create can't fail on a race.

Strict validation stays as it is: refusing a misnamed key is what catches `type` in place of `doc_type`.

Work on `fix/scout-review`. Per the usual rule, commit this plan as `docs/features/2026-10-11-import-save-errors.md` before any code. No new tests; fix only the existing tests a change breaks.

---

## M1: A refused save is short and says what to fix

**New middleware `SaveRefusal`** in `backend/app/ingest/middleware.py`.
- Applies to `save_research` and `save_vault_findings`.
- Inside `wrap_tool_call`/`awrap_tool_call`, when `handler` returns a `ToolMessage` with `status="error"` that starts with `Error invoking tool`:
  1. **Re-validate** `request.tool_call["args"]["findings"]` with `EntityResearch` / `VaultResearch` (`app/ingest/research_records.py`). This gives structured `e.errors()` (loc, type, msg), so there's no regex over the template.
  2. **Rewrite** the content to one line per problem, located by finding index, concept and the finding's name or title:
     ```
     Error invoking tool 'save_research': refused, nothing saved. Fix these 3 and send the whole payload again:
     - finding 27 (partner "The Ant"): source_type and evidence_tier come together: name both or neither
     - finding 126 (document "Financial reports index"): `notes` is not a field of document. Allowed: title, doc_type, as_of, evidence, source_url, source_name, confidence, basis. Put the remark in evidence or drop it.
     - top level: `replace` goes beside findings, not inside it
     ```
     - For an `extra_forbidden` error, the allowed keys come from that model's `model_fields`, so they can't drift from the schema.
- **Keep the failed-save signal intact.** Keep `status="error"` and the `Error invoking tool` prefix, so `save_failed()` / `EscalateAfterFailedSave` and `test_which_results_count_as_a_failed_save` still work.
  - Leave `REFUSED:` and `save_research failed:` replies untouched.
  - If re-validation passes (the error came from something else), return the original message.
- **Wiring** in `backend/app/ingest/agent.py`:
  - On the `entity-researcher` and the `vault-reader`, listed right after `filesystem_tools(...)`, so it runs inside the filesystem middleware's eviction and the short message is never moved to a file.
  - The vault reader has `evict=False`, so today it gets the full payload echoed inline.

## M2: The prompts ask only for fields that exist

**`backend/app/ingest/prompts/entity_researcher.md`** (and the matching lines in `prompts/vault_reader.md`):
- **Pairing, every run:** "`source_type` and `evidence_tier` go together, both or neither. On an organisation's findings, both are required."
- **Registrations:** "Status `registered` needs the number. Without it, use evidence_tier `claimed`, or `applied` with `application_ref`." This covers 6 of the 10 refusals.
- **Documents:** carry only `title`, `doc_type` and `as_of`. Remove the `fetched_at` mention at l.116.
- **`notes`:** only csr_year, csr_spend, footprint, partner, programme_spend, metric, contact, org_identifier and org_financials have `notes`. stated_geography and org_location have `note`. The rest have neither.
- **l.139:** "value, source URL, source name, fiscal year" becomes "where the concept has them".
- **`replace`:** it is an argument beside `findings`, never inside it.

**`research_goals`** (`backend/app/ingest/expectations.py`): add one line per concept, "Keys: …; any other key is refused", generated from the finding model's `model_fields`, including `source_type`/`evidence_tier` where they exist.
- Display only: the coverage counts (`expected_fields`, `TIER`) stay as they are, so "Fields 68/134" doesn't change.
- Also fix the `as_of` note (`expectations.py:324`) that names `fetched_at`.

Keep the phrases existing tests pin in both prompts (`tests/test_ingest.py`, and the parametrised prompt-per-spec test).

## M3: A preview writes nothing, and find-or-create survives a race

- **`backend/app/ingest/geography.py::_ensure`**
  - **Under `writer.GATE` with `plan=True`:** look up only. A missing row returns `-1`, the same placeholder `compare_with_catalog` already uses for a new entity, and inserts nothing.
    - A district under that state then doesn't resolve, which is exactly what a real save would do too (districts are never created).
  - **Otherwise:** `INSERT … ON CONFLICT DO NOTHING RETURNING id`, then re-SELECT when no row comes back. The untargeted `DO NOTHING` covers both `UNIQUE (kind, name, parent_id)` and the country's partial `locations_root_uniq`.
  - Same pattern as `writer.py:969`.
- **`save_to_catalog`** (`backend/app/ingest/tools/catalog_tools.py:708-729`): retry a row's transaction **once** on `psycopg.errors.UniqueViolation`.
  - Today one collision aborts the whole funder's promotion.
  - Every writer is find-then-insert, so the retry finds what the other session committed.
  - This covers `funders`, `funder_activity`, `programs`, `metrics`, `contacts` and the `org_*` tables without touching each one.
- **Out of scope** (no concurrent Import path hits them today):
  - duplicate `documents` with no unique key;
  - the case mismatch in `write_org_identifier`;
  - funder/org slug races.
  Note them in the plan doc.

---

## Verification

- `cd backend && .venv/bin/python -m pytest -m "not integration" -q` stays green, and `ruff check` passes on the changed files.
- **Replay** (scratch script, not committed): take the 10 refused payloads from the Langfuse traces, run each through the new middleware, and print the rewritten message. Each must:
  - be under 2 KB;
  - name the finding and the fix;
  - still count for `save_failed()`.
- **Preview:** run `compare_with_catalog` for a funder whose findings name a state that isn't seeded, e.g. Goa. The `locations` count is unchanged before and after (`make psql`).
- **Race:** two concurrent `resolve_location(conn, "Goa")` on separate connections both return the same id, with no exception.
- **Live:** one funder import through Scout. In its trace, any `save_research` refusal is a short list and the next save lands in a single retry.
