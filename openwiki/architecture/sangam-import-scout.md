---
type: architecture
title: Sangam Import (Scout)
description: How the Import agent (Scout on screen) is built after the ingest package split. A supervisor and four isolated subagents research funders and NGOs. Findings merge into one published brief per organisation, and catalog/promote moves the brief into the catalog through fixed-SQL writers with undo and human-in-the-loop pauses.
tags: [import, scout, ingest, deep-agent, brief, promote, writer, matcher, geography, undo, hitl, access]
sources:
  - id: openwiki-source-510f72ba91d3915e3fb10b24
    resource: repo://backend/app/agentkit/harness.py
  - id: openwiki-source-fe3601d35ecee292c4d2b24d
    resource: repo://backend/app/agentkit/middleware.py
  - id: openwiki-source-ca736c25c2a1bb0e95531706
    resource: repo://backend/app/api/routes/documents.py
  - id: openwiki-source-11c734346bddf773fd80ed0e
    resource: repo://backend/app/api/routes/ingest.py
  - id: openwiki-source-319a08aaeaf88078bae3e2e9
    resource: repo://backend/app/ask/agent.py
  - id: openwiki-source-4c1427c2f37a53fce3022d75
    resource: repo://backend/app/ask/skills/funder-matching/SKILL.md
  - id: openwiki-source-d55b72c3daac4208de6d9806
    resource: repo://backend/app/ask/tools/matching_tools.py
  - id: openwiki-source-933c62fa2383d76225c96eb5
    resource: repo://backend/app/core/egress.py
  - id: openwiki-source-70be5aeaef490fac42ba29bb
    resource: repo://backend/app/core/extract.py
  - id: openwiki-source-e136029ec7d24feaceb8ce72
    resource: repo://backend/app/core/lifespan.py
  - id: openwiki-source-b52886aad1fc413e4e030f22
    resource: repo://backend/app/core/security.py
  - id: openwiki-source-62958d5b14b0717233a7ec0b
    resource: repo://backend/app/ingest/agent.py
  - id: openwiki-source-7808196f4aecdc53b9018ae9
    resource: repo://backend/app/ingest/brief.py
  - id: openwiki-source-23397c01122692b0ff662a58
    resource: repo://backend/app/ingest/caller.py
  - id: openwiki-source-ad5981c88af1d87e4b3e6e70
    resource: repo://backend/app/ingest/catalog/matcher.py
  - id: openwiki-source-9a6e6a4e4a7cd8031491ea8d
    resource: repo://backend/app/ingest/catalog/promote_records.py
  - id: openwiki-source-da7e5350451b140c7b43eda3
    resource: repo://backend/app/ingest/catalog/promote.py
  - id: openwiki-source-538e8da8e6d92b2f24b1a6fa
    resource: repo://backend/app/ingest/catalog/save.py
  - id: openwiki-source-37b999e1f6fb5c4cc27629cd
    resource: repo://backend/app/ingest/catalog/undo.py
  - id: openwiki-source-b5f27a4e0b6c698c597d50c4
    resource: repo://backend/app/ingest/catalog/writer.py
  - id: openwiki-source-431ec8bbb35cd73df1e189b1
    resource: repo://backend/app/ingest/CLAUDE.md
  - id: openwiki-source-11c962d0a5a5a9bcbeea6cf5
    resource: repo://backend/app/ingest/geography.py
  - id: openwiki-source-117a8e2fc7d4a6bfc7ffb0b5
    resource: repo://backend/app/ingest/live_status.py
  - id: openwiki-source-7d480e75db10aae51a0f227b
    resource: repo://backend/app/ingest/middleware.py
  - id: openwiki-source-d1c2c2d698ef77e881e1ff17
    resource: repo://backend/app/ingest/news/verify.py
  - id: openwiki-source-602238f4e5bb2de7ed53155c
    resource: repo://backend/app/ingest/reading/access.py
  - id: openwiki-source-275d63cdc3d02cb975946728
    resource: repo://backend/app/ingest/reading/run_sources.py
  - id: openwiki-source-1de5a3e7ed2a11b942a4a84a
    resource: repo://backend/app/ingest/reading/vault.py
  - id: openwiki-source-ae8240491438531c1c77eff2
    resource: repo://backend/app/ingest/research/contract.py
  - id: openwiki-source-c925f927c5834f60b881dffa
    resource: repo://backend/app/ingest/research/findings.py
  - id: openwiki-source-7c81dc34ef98ea2bb422d08d
    resource: repo://backend/app/ingest/research/source_guards.py
  - id: openwiki-source-ef3ef9e2c9c396a73a96c4b8
    resource: repo://backend/app/ingest/reshelve.py
  - id: openwiki-source-5ca431fb0f110b9a36d2d445
    resource: repo://backend/app/ingest/tools/catalog_tools.py
  - id: openwiki-source-2df755596e53353deddeb8d3
    resource: repo://backend/app/ingest/tools/pipeline_tools.py
  - id: openwiki-source-51e6adf4243b3601b40e5803
    resource: repo://backend/app/ingest/tools/research_tools.py
  - id: openwiki-source-01018d1868720c2e42fdafe4
    resource: repo://backend/app/ingest/tools/vault_tools.py
  - id: openwiki-source-f298183777e9f6b64bb1b60f
    resource: repo://backend/tests/test_agent_middleware.py
  - id: openwiki-source-62d4dd57642429b3aa7980e3
    resource: repo://backend/tests/test_harness.py
  - id: openwiki-source-5ff63cf3bcc0508701587aa2
    resource: repo://backend/tests/test_import_undo.py
  - id: openwiki-source-92d175544a8e6396abecbd87
    resource: repo://backend/tests/test_ingest.py
  - id: openwiki-source-88fdf568b0f25b1d21f041da
    resource: repo://docs/CHANGELOG.md
  - id: openwiki-source-a44fe58bbddbee96fe925ba2
    resource: repo://docs/INGEST.md
generated: { by: "openwiki/0.7.2", at: "2026-11-10T13:16:49.280Z" }
verified:
  - by: openwiki/0.7.2
    at: 2026-11-10T13:16:49.280Z
---

# Sangam Import (Scout)

Sangam Import is a second LangGraph deep agent, separate from [Ask Sangam](ask-sangam.md). Ask reads the catalog. Import builds it. Users see it as **Scout** at `/import`. The backend and prompts call it "ingest", threads are named `import-<uuid>`, and the graph is built by `build_ingest_agent()` in `backend/app/ingest/agent.py`. Its Langfuse trace name is `sangam_import`.

The agent never writes SQL. It proposes typed findings, and fixed-SQL code under `app/ingest/catalog/` does every write. A test asserts that no supervisor tool name contains `query` or `sql`.

> **Source of truth.** `docs/INGEST.md` predates PRs #192–#197 and its header (lines 9–27) lists what is wrong in it. Trust the code, this page and `docs/ARCHITECTURE.md` §4. `backend/app/ingest/CLAUDE.md` says the same: facts about agents, tools, middleware and skills live in this page, rules and decisions live in `ARCHITECTURE.md` §4 and §6, and where `INGEST.md` disagrees, source and the wiki are right. A changed tool or flow means regenerating the wiki (`make wiki-update`). A changed rule means editing §4. `INGEST.md` also still names the pre-split module paths.

## Where the code lives

The ingest package was split by what a module does (CHANGELOG #372–#374). Use these paths, not the older flat ones:

| Package | Holds | Role |
|---|---|---|
| `app/agentkit/` | `harness.py`, `middleware.py`, `models.py` | Pieces every deep agent shares: the harness profile and filesystem restriction, `tool_errors`, `clear_old_tool_results`, `fallback`, `cheap_summarizer`, and `resolve_model`. Ask, Import and Sangam Pitch all use it. It was `app/agent/` before the split, and Ask's own code is now `app/ask/`. |
| `app/ingest/` (top level) | `agent.py`, `middleware.py`, `brief.py`, `caller.py`, `geography.py`, `live_status.py`, `reshelve.py`, `runner.py`, `instructions.md`, `prompts/`, `skills/` | The graph, Import's own middleware (including `StaffLastLock` and `SaveQuestions`), the brief, the caller scope, the geography resolver and the adapter runner. |
| `app/ingest/tools/` | `catalog_tools`, `library_tools`, `pipeline_tools`, `research_tools`, `vault_tools` | Every tool the model can call, and nothing else. |
| `app/ingest/research/` | `contract`, `coverage`, `expectations`, `finding_types`, `findings`, `source_guards` | What a researcher must answer and how a save is judged. |
| `app/ingest/reading/` | `access`, `registry`, `run_sources`, `staff_sources`, `vault` | Where a run may read from: URL checks, the source registry, the person's source choice, staff workbooks and the Doc Vault. |
| `app/ingest/catalog/` | `save`, `promote`, `promote_records`, `promote_documents`, `promote_facts`, `writer`, `writer_funder`, `writer_org`, `matcher`, `undo`, `review`, `rows`, `manual_checks` | From the brief to Sangam's tables. |

`test_architecture.py` caps a source file at 800 lines, which is why `promote` and `writer` were divided.

## The agents

One supervisor delegates to four subagents. Every subagent is `mode="isolated"` with its own context window. The reason is context, not speed: one broad research turn once read three PDFs across about twenty calls and never reached its report. An isolated subagent returns a conclusion, not its reading.

| Agent | Model tier | Tools | Role |
|---|---|---|---|
| supervisor | `MODEL` (strong) | `list_import_sources`, `plan_import`, `run_import_now`, `import_run_summary`, `pending_resolutions`, `choose_sources`, `funder_dossier`, `compare_with_catalog`, `coverage_report`, `record_registry_check`, `publish_brief`, plus `read_file`, `ls`, `task`, `write_todos` | Plans in waves of `MAX_PARALLEL_RESEARCH`. Has no web tools and researches nothing. |
| `entity-researcher` | `RESEARCH_MODEL` | `research_goals`, `funder_dossier`, `list_library_documents`, `read_library_document`, `read_source_rows`, `search_public_sources`, `read_page`, `fetch_document`, `read_document_pages`, `save_research`, plus `read_file` | One per organisation. Reads its pull skill, researches, then saves. Returns a thin `ResearchSummary`. |
| `vault-reader` | `RESEARCH_MODEL` | `list_vault_documents`, `read_vault_document`, `research_goals`, `save_vault_findings`, plus `read_file` | Reads one organisation's private Doc Vault files before the web. Has no web tools. |
| `catalog-writer` | `UTILITY_MODEL` | `promote_research`, `funder_dossier`, plus `read_file` | Promotes one saved organisation, reads the catalog back, reports a `PromotionReport`. Cannot research. |
| `workbook-reader` | `UTILITY_MODEL` | `read_workbook`, plus `read_file` | Lists the organisations named in picked staff spreadsheets so the supervisor can launch one researcher per name. |

Key design points:

- **Tool lists are fixed and pinned by tests.** `test_ingest.py` checks that the instructions name every supervisor tool and that each subagent prompt names every tool its spec declares. It also checks that every `@tool` in `app/ingest/tools/` is registered somewhere, and that registered tools live only in that package. `test_harness.py` compiles the graph, asserts the four compiled subagents by name, and compares the real tool sets of the entity-researcher, the vault-reader and the catalog-writer to exact literals (the workbook-reader has no literal there). Separately, `test_import_advertises_exactly_its_two_subagents` (despite its name) only asserts that `entity-researcher` and `catalog-writer` appear in the `task` tool's advertised list and `general-purpose` does not. It does not check an exact set; the exact four are asserted by `test_both_subagents_are_compiled_and_found`.
- **Every subagent carries its own `filesystem(...)` middleware.** An isolated subagent builds its own middleware stack, so the parent's restricted filesystem never reaches it. Left to the library, each subagent would get all eight filesystem tools, including writes against a backend whose `/skills/` route is real disk. `app/agentkit/harness.py` therefore exposes only `read_file` on subagents. The supervisor also keeps `ls`, which is how it recovers a stale skill path. `install()` also disables deepagents' `general-purpose` subagent, registered per provider. That subagent would otherwise carry the supervisor's whole tool list, including `run_import_now` and `promote_research`.
- **The supervisor writes almost nothing.** Its only writes are `record_registry_check` (a staff member's manual registry check) and `run_import_now` (the bulk pull). `run_import_now` branches on `sources`: `tavily_news` runs a news pull for named Registry records or topic feeds and never creates a funder or organisation, `funder_calls` runs the open-calls pull for [RFP Watch](rfp-watch.md), and each of those runs alone (any other source named in the same call is refused out loud). Anything else goes through the generic adapter runner (`runner.py`). All of it is staff-only and behind an approval card. `research_goals` is deliberately left to researchers, because it requires an `entity_kind` and refuses `unknown`.
- **Prompts are markdown beside the code.** `instructions.md` is the supervisor prompt and `prompts/*.md` are the subagent prompts. The only substitution is `{{MAX_PARALLEL_RESEARCH}}`. It is rendered from the `Settings` the graph was built with, so raising the setting changes what the model is told, and a test pins this.
- **Tools never raise.** Failures come back as strings (`REFUSED: …`, `… failed: <ExceptionType>`). Where a failure could quote a confidential cell or file, only the exception type is returned.

## Middleware

Import's own middleware is in `app/ingest/middleware.py`, including `StaffLastLock` and `SaveQuestions` (they used to sit beside Ask's middleware, and only Import ever used them). The shared pieces come from `app/agentkit/middleware.py`.

| Middleware | On | What it does |
|---|---|---|
| `tool_errors` | supervisor and all four subagents | `ToolErrorMiddleware` backstop for the "tools never raise" convention: a tool that raises past its own try/except answers the model with `<tool> failed: <ExceptionType>` instead of ending the run. |
| `CallerNote` | supervisor | Appends one line saying who the run works for and what they may do. Tools still enforce it. |
| `TickedSources` | supervisor | Reads the sources the person ticked from AG-UI context, tells the model, and overwrites the arguments of its `choose_sources` call with them. |
| `ChosenSources` | supervisor | Refuses every `task` launch until `choose_sources` has been answered, then publishes that answer to the subagent through the `run_sources.CURRENT` context variable. Unreadable state fails closed. |
| `RunSources` | researcher, vault-reader, workbook-reader | Refuses any pulling tool outside what the person chose. A subagent running outside a `task` reads nothing. |
| `SaveRefusal` | researcher, vault-reader | Turns a pydantic error on `save_research` or `save_vault_findings` into a short list of fixes. It also accepts a payload sent as a JSON string. |
| `StaffLastLock` | researcher | Once `read_source_rows` has been requested, including in the current turn, every tool outside the `OPEN_AFTER_STAFF` allowlist gets an error reply ("web tools are closed for this run: staff rows have been read. Save what you have."). The allowlist is `read_source_rows`, `save_research`, `read_document_pages`, `research_goals`, `funder_dossier` and `read_file`. An outbound tool added to the researcher later is therefore closed by default, and unreadable state fails closed. The aim is that an injected instruction on a web page cannot carry a staff row out in a URL or query. |
| `ReadingLimit` | researcher only | Caps page reads. Added only when `RESEARCH_PAGE_LIMIT` is set (it is not by default). The vault-reader, the catalog-writer and the workbook-reader have no reading limit. The class is defined in `app/ingest/middleware.py`, and the separate news-verification agent (`app/ingest/news/verify.py`) reuses it with its own limit. That agent is not part of Import's graph. |
| `clear_old_tool_results` | supervisor | Shared with Ask and Sangam Pitch (defined in `app/agentkit/middleware.py`). Past 60,000 tokens it replaces the oldest tool results with `[cleared]`, keeping the latest five. See below. |
| `call_limit` | researcher, vault-reader, writer | Caps model calls. On the researcher and vault-reader it is added only when `RESEARCH_MODEL_CALL_LIMIT` is set (not by default). The writer always has a limit of 12 calls (`WRITER_MODEL_CALL_LIMIT`). The workbook-reader has neither limit. |
| `EscalateAfterFailedSave` | researcher | After one malformed save, the rest of the run uses the strong model. Added only when the research model differs from `MODEL`. |
| `fallback` | all | On a failed call, switches to the next tier's model. |
| `ResearchRubric` | researcher | A utility-model grader checks the save and summary against `prompts/research_rubric.md`, with at most one revision. It skips grading when a call limit ended the run. |
| `cheap_summarizer` | supervisor, researcher | Same thresholds as the agent's own model, but summaries are written by the utility model. |
| `DropFilesOnExit` | vault-reader | Deletes every file in the subagent's state as it ends, so offloaded vault text cannot flow back to the parent and on to a researcher. |
| `SaveQuestions` | catalog-writer | Pauses every `promote_research` (see below). |
| `run_plan` | supervisor | `TodoListMiddleware` with a short custom `write_todos` prompt. The plan survives summarisation. |

The vault-reader's filesystem is built with eviction off (`evict=False`), for the same reason `DropFilesOnExit` exists. The researcher's lowers the eviction threshold to 8,000 tokens (`RESEARCHER_EVICT_AT`) so long pages go to a file it pages back with `read_file`.

### Shared tool-result clearing

The supervisor's stack includes `clear_old_tool_results()`, the same `ContextEditingMiddleware` factory Ask and Sangam Pitch use. It is not applied to any Import subagent. Its constants live in `app/agentkit/middleware.py`:

- `TOOL_RESULT_CLEAR_TRIGGER_TOKENS` = 60,000: below this nothing is cleared.
- `TOOL_RESULTS_KEPT` = 5: the most recent results always stay, because a follow-up refers back to them.
- `TOOL_RESULTS_CLEAR_STEP` = 20,000: `SteppedClearToolUsesEdit` reclaims whole steps beyond the trigger. A fixed amount would clear the same few results forever, and the request would keep growing. With steps, what is sent stays under the trigger and the cleared set, and so the cached prompt prefix, moves only once per step.
- `NEVER_CLEARED` = `compare_fit`: an Ask tool the Import supervisor does not have, so it matters here only through the shared edit.

`test_agent_middleware.py` pins this behaviour: under the trigger nothing is cleared, sent tokens stay under the trigger however long the turn, cache breaks are bounded by the number of steps, and the latest results and `compare_fit` survive.

The funder-matching, funder-comparison and funder-shortlist-brief skills (`app/ask/skills/`) and `compare_fit` (`app/ask/tools/matching_tools.py`, registered in `app/ask/agent.py`) belong to Ask's runtime, not Import's. The Import supervisor's own dry-run comparison is `compare_with_catalog`. See [Ask Sangam](ask-sangam.md) and [Funder Match](funder-match.md).

## Human-in-the-loop pauses

There are three pauses.

1. **`choose_sources`** is in `INTERRUPT_ON` with approve, edit and reject. Its `when` predicate, `ask_for_sources`, shows the card only if nothing was ticked before sending, because a tick is already the person's answer. Rejecting the card means public websites only (`WEB_ONLY`).
2. **`run_import_now`** is in `INTERRUPT_ON` with approve and reject. It is the supervisor's one bulk write.
3. **`promote_research`**, through `SaveQuestions` on the catalog-writer. The pause carries a preview of the funder's open questions, planned rows and a coverage line (built by `catalog/save.write_preview`). The person's answers arrive as an `edit` whose args hold `decisions`. Any `decisions` the model wrote itself are overwritten, so only a person can set them.

The run resumes with `Command(resume={"decisions": [...]})` from the Import screen. The frontend side is described in [Frontend](frontend.md).

## One turn

```mermaid
sequenceDiagram
    participant P as Person
    participant S as Supervisor
    participant R as entity-researcher
    participant B as Brief in Storage
    participant W as catalog-writer
    participant C as Catalog
    P->>S: message plus ticked sources
    S->>P: choose_sources pause if nothing ticked
    P-->>S: sources answer
    S->>R: task per organisation, in waves
    R->>R: research_goals, read pages, quote evidence
    R->>B: save_research then brief.publish
    R-->>S: ResearchSummary
    S->>W: task per saved organisation
    W->>P: promote_research pause with questions
    P-->>W: approve with decisions
    W->>C: promote inside one undoable transaction
    W->>B: write fact states back into the brief
    W-->>S: PromotionReport
```

Caption: the main path of an Import turn from sources to catalog. The vault-reader and workbook-reader steps, which run before the researcher, are omitted. See [Import turn](../workflows/import-turn.md) for the step-by-step flow.

Ordering rules that hold across a turn:

- `choose_sources` comes first and alone, except for a news pull or a `publish_brief` republish. The answer lives only in the checkpoint, as the tool message's artifact (`run_sources.chosen`).
- When the Doc Vault was picked, a `vault-reader` runs before the researcher. It hands back only concept names and ids, never file text, and the researcher is told which concepts are still missing.
  - `app/ingest/reading/vault.py` reads an organisation's private `org-vault` uploads of several types: PDF, Word (`.docx`), PowerPoint (`.pptx`), `.xlsx`, CSV, Markdown/text (`.md`, `.txt`) and PNG, JPEG or WebP images. Each line is cited by a marker: `[vault:<id>#p<page>]` for a PDF page, `[vault:<id>#para<n>]` for a Word paragraph, `[vault:<id>#slide<n>]` for a slide, `[vault:<id>#line<n>]` for a text or CSV line, `[vault:<id>#<sheet>!<cell>]` for a workbook cell and `[vault:<id>#image]` for an image. Any other file type returns a "cannot be read here" message.
  - A text read is capped at 24,000 characters (`MAX_CHARS`), so the text never needs evicting to a file. Continuation uses `start_page`, which counts paragraphs in a Word file, slides in a PowerPoint file and lines in a text or CSV file (a later CSV window repeats the column names). A PDF with no extractable text is reported as probably scanned, never guessed at. An image comes back to the model as the picture itself (a base64 image block, capped at about 3.75 MB), not as text.
  - `save_vault_findings` refuses the whole save unless every finding cites a document in that organisation's vault, by `https://org-vault.sangam.invalid/<id>` URL and its `[vault:<id>#…]` marker. Findings go to `vault_research`, one row per slug, org and day (`ON CONFLICT (slug, researched_on, org_id)`), never to `entity_research`. An NGO save also needs `can_research_org`.
- When the request is about everyone in a staff file, a `workbook-reader` returns the names, and one researcher per name follows.

## The research contract

The researcher's contract is enforced in code, not only in prose.

1. **Typed findings.** `EntityResearch` (`research/findings.py`, with the per-concept models in `research/finding_types.py`) forbids extra fields. It rejects `complete` with no findings, `partial` or `wrong_entity` with no `stopped_reason`, and `unknown` kind alongside findings. It requires an NGO's programmes, metrics, contacts and partners to carry `source_type` and `evidence_tier`.
2. **Honest source labels.** `research/source_guards.py` requires a value from an aggregator or from the team's earlier research to be saved as `claimed`. `EntityResearch` runs that check as a validator, so a mislabelled save never reaches the tool body. The same check re-runs at promotion, and the fact is held if its table cannot mark a value claimed.
3. **`contract.unanswered()`** (`research/contract.py`) refuses a save in which a concept of the kind's list has neither a finding nor a gap. Yearly concepts need one per asked fiscal year, defaulting to the most recent three. Identity fields need a value or a gap, and `themes` is required.
4. **Pull skills.** The researcher reads `/skills/research/<kind>/SKILL.md` for the field list it must answer. Only the researcher sees them. Constraints never live in a skill, because loading a skill is the model's choice.

```mermaid
flowchart TD
    A["save_research called"] --> V{"schema and source guards pass"}
    V -- no --> X1["refused with list of fixes"]
    V -- yes --> K{"NGO and caller neither staff nor steward"}
    K -- yes --> X2["REFUSED: NGO research"]
    K -- no --> U{"contract.unanswered is empty"}
    U -- no --> X3["REFUSED: finding or gap missing"]
    U -- yes --> M{"NGO and non-staff caller does not steward the matched NGO"}
    M -- yes --> X2
    M -- no --> D{"same slug already saved today by someone else"}
    D -- "yes and not staff" --> X4["REFUSED: today's research is on file"]
    D -- no --> S{"fewer findings than stored and replace not set"}
    S -- yes --> X5["REFUSED: would shrink the result"]
    S -- no --> O["upsert entity_research on slug and day"]
    O --> P["brief.publish merges every run into the brief"]
```

Caption: the checks a save passes before it lands. The NGO check runs twice: first on the caller's roles alone (staff or a steward of some organisation), then, once the database is open, against the specific NGO the save resolves to (`_may_research`, which needs `can_research_org` for every organisation row it matches). When a save carries staff-spreadsheet findings, a failure returns only the exception type. The tool then reports numbers found only inside quotes, so the researcher can add them as findings.

A save upserts `entity_research` on `(slug, researched_on)`. The one row per entity per day is shared, so only staff replace what someone else saved today. The number of findings may not shrink without `replace=true`. That rule exists because a short re-run once silently overwrote a long one.

## The brief is the record

The durable record for an organisation is its **published brief**, a markdown file at `source-archive/entities/<slug>.md` in Supabase Storage. **There is no brief table.** `entity_research` rows are per-run inputs. The brief is what promotion reads.

How `brief.py` works:

- **Hidden fact blocks.** Each fact line carries its typed finding in an HTML comment, `<!-- fact {json} -->`. `--` is escaped so a value cannot close the comment. `record()` reads facts and unplaced facts back from these blocks.
- **Merge by `fact_key`.** `build()` reads the published brief, then merges every research row for the slug on top. A later run replaces an earlier one for the same key unless the earlier source is strictly stronger (evidence tier first, then confidence). Ties go to the later run. A `wrong_entity` row adds nothing.
- **Unplaced facts.** A fact no field can hold goes in an `<!-- unplaced -->` block under "Stated, but Sangam has no field for it". It exists only in the brief.
- **Fact states.** After a save, `promote()` reports a state per fact. Each state is written back into the fact's block and shown as an "In Sangam:" line. The states are written, confirms, conflicts, waiting, kept, skipped, held and no column. A fact keeps its last state until it is promoted again.
- **Failure behaviour.** If Storage cannot be read, `build()` raises and the existing brief is left untouched. `save_research` still succeeds and reports the brief as unpublished. When Storage is not configured, `publish_markdown` is a no-op. Writing states back after a catalog commit is best-effort, and failure is only logged.
- **Private findings never enter the brief.** Findings whose `source_url` is on the reserved `sangam.invalid` domain (staff datasets and the Doc Vault, recognised by `source_guards.is_private_source`) are filtered out of the brief, and the summary is replaced by a fixed private note.
- **`promotable()`** returns the newest row with every fact the brief holds, or would hold once all runs are merged. It also adds that row's own private findings, which the brief never holds. Findings without a `concept` (the pre-typed shape) are dropped, because nothing could write them.

## Saving and `promote()`

Saving has two entry points. The Review screen calls `POST /api/ingest/research/{slug}/save`. A chat request such as "save X" goes through the catalog-writer and `promote_research`. Both call `save_to_catalog()` in `catalog/save.py`; the tool and route modules only wrap it.

For each organisation, `save_to_catalog()` opens one transaction:

`undo.start` → `promote()` → `_record_save` → `undo.finish`

It retries once on a `UniqueViolation`, which happens when a concurrent save inserted the same row between a look-up and its insert. After commit it writes fact states back into the brief. Without a slug only staff may promote everything. Others must name one organisation. For a non-staff caller `_may_save` also checks the role: any signed-in user may save a funder, but an NGO must already be one Sangam holds (the Sangam team adds new NGOs) and the caller must steward it.

`promote()` in `catalog/promote.py` runs in this order:

1. **Source guards** hold findings before any branch runs:
   - Research saved under an older finding shape (below `TYPED_SINCE`) is not promoted at all. Re-running the research is the remedy.
   - Staff-dataset findings need a `[source:…]` cell marker for their own dataset. A figure must also match the cited cell in its unit (`staff_sources.hold_unmarked`, `hold_mismatched`).
   - Vault findings are checked by `vault.hold_at_promote`. For a funder only general facts pass, and for an NGO none do.
   - `source_guards.hold_at_promote` re-checks aggregator labelling.
2. **Kind branch.** `_promote_funder` or `_promote_org`, which reach different tables through different resolvers.
3. **Funder path**, in this order:
   - Resolve the entity, preferring the one an earlier save wrote to. A trigram-only match becomes a question the person answers.
   - Reconcile the record with what the `funders` row's constraints would refuse (a CIN that names a company rather than a foundation, a CIN already held elsewhere, an inverted grant band). Each is reported as held.
   - Resolve the parent company (`_parent`). A parent that is not in the catalog is reported as held, never created.
   - Write the funder, then its tags.
   - Write a `documents` row for every public source a fact cites. A dry run skips this, because archiving moves storage objects that no rollback undoes.
   - Write the CSR years.
   - Write programmes parents-first.
   - Write the facts in `WRITE_ORDER` (`csr_spend`, `footprint`, `stated_geography`, `partner`, `programme_spend`, `metric`, `contact`, `rfp`, `eligibility_guideline`).
   - Write `document_links` and link the research row to the funder (both skipped in a dry run).
4. **NGO path** (`_promote_org`). Same shape, with differences:
   - It resolves an NGO's parent body (`_org_parent`), which links only a parent Sangam already holds, and otherwise reports the link as held, never a new row.
   - It reconciles aliases so a spelling another organisation already answers to is held rather than shared.
   - After writing the org it links funder partner lines that already named it.
   - It writes tags, documents and programmes, then facts in `ORG_WRITE_ORDER` (`org_identifier`, `org_financials`, `org_location`, `metric`, `contact`, `partner`), then `document_links`. There is no CSR-year step, and every finding carries a tier.
   - `gate` is set to `None` for orgs. They keep fill-blanks with evidence-tier ranking and report conflicts, and a name resembling a stored NGO becomes a Review question.
5. **Settling.** Every fact ends in exactly one state. `unsettled` assigns "no column" or "held" with a reason to any fact no writer reached. Nothing is dropped silently.

## The writer and its Gate

`catalog/writer.py` (with `writer_funder.py` and `writer_org.py`) is the only place Import writes, always with fixed SQL. It never overwrites a stored value with `NULL`. A funder's updatable columns are an explicit list, so hand-vetted columns are left alone.

When a `Gate` is set, every funder write falls into one of five cases:

| Case | Situation | Outcome |
|---|---|---|
| 1 | Same value | Counted as `same`, nothing to do. |
| 2 | Same row, source as recent or newer | Updates without asking. |
| 3 | Same row, older or undated source | Asks the person: update or keep. |
| 4 | Close but not exact name (checked by `close_names` against `CLOSE_MATCH` tables) | Asks the person: update, new or skip. |
| 5 | Nothing close | Inserts without asking. |

A change confined to provenance columns (`NOT_FACTS`) is the same fact re-read and never a question. Question ids are hashes of the case, table and named key, excluding database ids. An answer therefore survives between the plan and the apply, even when a programme only has a real id at apply time. `Gate(plan=True)` writes nothing. `compare_with_catalog`, `coverage_report` and the review card use it for dry runs. Unanswered questions are held, not saved.

## The matcher

`catalog/matcher.resolve_funder` tries, in order: CIN, exact name, alias, name variants, website domain, boilerplate and finally trigram. A CIN hit counts only if the names also look like the same organisation, because filings attach to a parent. The website step has the same requirement, since a company and its foundation can share a site.

Five match methods resolve and merge: `MERGEABLE` in `promote_records.py` lists `identifier`, `exact`, `alias`, `boilerplate` and `website`. Name variants such as a parenthetical abbreviation report as `alias`. A trigram match only proposes, and a person accepts it as a Review question. `resolve_org` follows the same ladder (with a normalised name-or-alias step before boilerplate), and its identifier step skips `reg_no` because state-society registration numbers repeat across registrars. Names compare on their distinctive core after dropping words such as "Limited" and "Trust". A single-token core is not enough to treat two foundations as the same, so a company-versus-foundation difference is respected.

## Geography

`geography.py` resolves state and district names against a closed list: 28 states and 8 union territories, and the LGD districts seeded in `locations`. It is never allowed to invent a district.

- An unknown state is refused with a reason.
- A district with no state is refused.
- A district matches by normalised name, then alias.
- A near match is taken only when it clears `NEAR_FLOOR` (0.4), leads the runner-up by `NEAR_MARGIN` (0.15) and agrees on direction and size qualifiers such as north, rural and urban. Otherwise it is held for a person, and the reason names the alias CSV to extend.
- The only rows it may create are the country and a canonical state, and only under a real write. A preview returns `-1` instead.

## Undo and delete

`catalog/undo.py` is staff-only, and the routes enforce that.

- `start` inserts a `promotions` row and sets `sangam.promotion_id` for the transaction, which turns on the write log. Database triggers record `catalog_writes` only while it is set. `finish` stops logging and deletes the promotion if nothing was written.
- `undo()` replays `catalog_writes` newest first, in one transaction. It deletes inserted rows and restores updated rows from their logged `old_row`.
- It **refuses the whole undo**, returning HTTP 409 and changing nothing, if any row differs from how the save left it, is now referenced elsewhere, or sits in a table outside `LOGGED`. `LOGGED` lists 19 tables. Rows are compared as `jsonb` in SQL because a round trip through Python would turn numerics into floats.
- Undoing a creation unlinks `entity_research.resolved_funder_id` or `resolved_org_id` first, and clears `saved` once no live save of that research remains.
- `delete_research` removes the `entity_research` and `vault_research` rows for a slug, but returns `None` while a save of it stands, so a save must be undone before the research is deleted.

`test_import_undo.py` covers this: a logged save then its undo, refusal when a row changed since, restoring an update, amounts too precise for a float, writes outside a save not being logged, a save that wrote nothing leaving no promotion, and a save from the screen being logged and undone.

## Access

Import is for Sangam staff and for stewards of an organisation. Within that group, some routes and tools are staff-only. For wider context see [Auth, roles and RLS](auth-roles-rls.md).

- **The Scout gate.** `require_scout` (`app/core/security.py`) returns 403 ("Scout is for stewards and Sangam staff") unless the caller is staff or steward of at least one organisation. It is a router-level dependency on every `/api/ingest` route, and `AGENT_ACCESS` in `app/core/lifespan.py` pairs it with `chat_access` for the `/ingest` agent endpoint. A signed-in member or admin who is not a steward therefore cannot reach Import at all. Ask uses `ask_access` instead, and its SQL runs as the caller.
- **Owner pool and `chat_scope`.** Agent tools run on the owner pool, so Postgres RLS does not apply. `chat_access` sets a `chat_scope` context variable holding a `CallerScope` (staff flag, org roles, steward list). `ingest/caller.py` reads it, and outside a chat request it yields a caller with no access. Each tool checks the scope itself:
  - `staff_only(tool)` returns a `REFUSED` string for `run_import_now`, `plan_import`, `import_run_summary`, `pending_resolutions`, `read_source_rows`, `read_workbook`, `publish_brief` and `record_registry_check`.
  - `can_read_org` gates Doc Vault tools. A file the caller cannot read gets the same answer as a file that does not exist.
  - `can_research_org` gates NGO research and saves to stewards and staff. Other roles research funders only.
  - `can_save_funder` needs a signed-in user.
- **Private findings are stripped for non-staff.** Staff-spreadsheet and vault findings are removed from research rows by `without_private` and are never rendered into the brief, which replaces the summary with a fixed private note when a run read private sources. `save_to_catalog` and the review, coverage and save routes read rows through the same caller-scoped `research_rows` filter, and a vault finding is visible only to a caller who can read that organisation.
- **Staff spreadsheets and Doc Vault.** Staff picks are refused for non-staff in `choose_sources`. Vault picks must belong to an organisation the caller can read and must exist in that organisation's vault. `RunSources` further limits reads to the picked ids.
- **Egress.** `reading/access.check_url` runs before every research read and is never raising. In order:
  1. http(s) scheme only.
  2. No URL credentials.
  3. `private_address_refusal`, which blocks private, loopback, link-local and metadata addresses before and after DNS.
  4. The source registry's access rule. A held source is a dead end, and the message tells the agent not to look for another route.
  5. `robots.txt`. An unreadable file is not permission for an unclassified host, while a host a person has already classified keeps that decision. A 5xx response counts as unreadable, and a 4xx response as no restrictions.
  
  `robots.txt` itself is fetched with `guarded_client`. The page and document downloads use a client whose request hook runs `check_url` on every redirect hop before it is followed. Hosts that are readable but unclassified are recorded in `ingest_source_proposals`, best-effort. Newly read pages and documents are archived to the `source-archive` bucket.
- **Routes.** Behind the Scout gate, `overview`, `research` list, review, coverage and save use `request_scope` and are scoped to the caller. A non-staff list sees only what the caller saved plus research on NGOs they steward, with private summaries replaced and `promotion_id` and `saved_by` blanked. `overview` returns the whole Import page in one request and gives non-staff empty sources, runs, queue and proposals. The source registry (`/sources`, `/proposals`), runs, queue, workbooks list, undo and research delete are `require_staff`. Only staff receive a `promotion_id` from a save. A refused save is HTTP 403.

## Mid-run status questions and housekeeping

- **`POST /api/ingest/threads/{thread_id}/ask-live`** answers a question asked while a run is still going. `live_status.answer` reads the run's checkpoint (the request, ticked sources, launched researchers, their returns and the todo plan), the caller's research saved since the run began, and the Working board's per-researcher counts, then asks the utility model for a `status` or `instruction` reply using `prompts/live_status.md`. It never touches the running graph, and it is limited to the caller's own `import-` threads.
- **`python -m app.ingest.reshelve`** (dry run by default, `--yes` to move) renames archived documents from their fetch-time key to the catalog name `funders/<slug>/<year>-<filename>`, reusing `catalog/promote_documents._shelve`. It catches objects archived before promotion learned to rename them.

## Office text extraction

`app/ingest/office.py` no longer exists. The text helpers now live in `app/core/extract.py` (pure bytes to text: PDF, Word, Excel, PowerPoint and text files) and are shared by several callers:

- **Document upload.** `_extract` in `app/api/routes/documents.py` uses `extract.docx_paragraphs` (paragraphs, with each table row as `a | b | c`, in document order), `extract.pptx_slides` (each slide under a `## Slide n` heading), `extract.xlsx_markdown` (each sheet as a heading plus its first `SHEET_ROWS` = 200 rows) or `extract_pdf_text` to fill `content_md` for a new upload. CSV, text and image uploads get no `content_md`. A damaged file leaves the text empty and the upload is still stored with its hash. Before extracting, the route checks that the file's leading bytes match its extension (`_bytes_match`) and refuses a mismatch with 415.
- **Vault reading.** `vault.docx_text` and `vault.pptx_text` number `docx_paragraphs` and `pptx_slides` for citation, and `vault.plain_text` numbers a text or CSV file's lines (`extract.text_lines` splits any line over 2,000 characters). Workbooks go through `staff_sources` rendering with a `vault` marker, so the vault-reader can page past the 200 rows an upload keeps. `vault.pdf_text` uses `extract_pdf_text`.
- **Researcher downloads.** `read_document_pages` uses `extract.docx_range` for a downloaded Word file and `extract_pdf_text` for a PDF.

## Skills

Skills live in `app/ingest/skills/` and ship with the code. The backend is a `CompositeBackend`: virtual state for everything, real disk for `/skills/` alone, in `virtual_mode` so path traversal cannot read the host.

- **What to pull** is `research/funder-intake-research` and `research/ngo-credential-research`. Only the researcher sees them, and a test pins the set.
- **What to produce** is `entity-record`, `funder-scan-for-fundraisers` and `ngo-brief-for-funders`.
- **What the catalog did** is `catalog-mapping` and `catalog-write-report`.

The supervisor indexes five skills. The subfolder keeps the pull skills out of its listing.

## Unfinished and stale

From the CHANGELOG "Not finished" table and `docs/INGEST.md`:

- The researcher-contract plan (`2026-10-13-import-researcher-contract.md`) shipped M1–M4. **M5**, a backfill of two organisations on staging, is not done.
- The programme-themes plan shipped steps 1–4. Step 5, `write_funder_tags_from_programs` (PR #172), is unmerged.
- The access plan shipped Phase 1. The CHANGELOG still says Ask's SQL and Import run on the owner pool, but the code has moved on: `ask_access` sets `agent_caller`, so Ask's SQL runs as the caller. Import deliberately keeps the owner pool, because it writes the catalog. This is why every Import tool checks scope itself.
- `2026-10-09-import-guided.md` shipped in #130, but its review follow-ups list is still open.
- `docs/INGEST.md` is out of date on the record (brief, not one row), the pauses, the tool modules (five), `StaffLastLock`, who may use Import (staff and stewards, via `require_scout`, not any signed-in user), the researcher's order, the matcher order, districts, the NGO path, undo's table count, the `/ingest` endpoint wiring, the source count (80, not 79) and the known gaps (the registry-check tool and `csr_sector_id` now exist). It also predates the module split described at the top of this page.

## Where to change things

- **A supervisor or subagent tool.** Add the function in `app/ingest/tools/`, register it in `TOOLS` or a subagent's tool list, and name it in `instructions.md` or the subagent prompt. Update the literal tool-set tests in `test_ingest.py` and `test_harness.py`.
- **A new concept or field.** Edit `research/finding_types.py` and `research/expectations.py`, then add a branch in `brief.headline`, a record type in `CONCEPT_RECORDS` (`catalog/promote_records.py`) and a writer in `catalog/writer*.py` and `catalog/promote_facts.py`.
- **A new logged table.** Add it to `catalog/undo.LOGGED` together with the migration's trigger.
- **Middleware every agent shares.** Change `app/agentkit/`, and remember Ask and Sangam Pitch pick it up too.

Related: [Data and migrations](data-and-migrations.md), [Media and signals](media-and-signals.md), [Testing overview](../testing/overview.md).
