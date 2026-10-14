# Proposal Copilot: a human-in-the-loop agent that builds a proposal with the NGO

Draft v1 · 2026-10-14 · branch `feat/proposal-copilot`

**Replaces** the 9 Oct proposals spec (`features-plans/proposals/2026-10-09-proposals-design.md` on
`docs/proposals-spec`, never merged). These parts of that spec carry over unchanged:

- gates G1/G2;
- template and writing style;
- rubric `proposal-v2` with A/B/C/F display codes;
- assemble → polish → .docx with versions;
- PATCH `work` by path with a section `rev`;
- several proposals per org and funder;
- stewards and staff can write.

What it replaces is "draft every section at once with ~20 fixed calls". The UI was agreed on the Guided prototype
(https://claude.ai/artifact/VcqNEkToJbDZk67fDCkvYF). Every path below was checked against `origin/master` at
`9e7e6f0`. The running example is SeSTA (the NGO) writing to Axis Bank Foundation (ABF, the funder).

## 1. Requirement summary

- Once an NGO is matched with a funder, an agent guides them to a strong proposal for that funder. It is not a one-shot generator.
- **It reads what Sangam already holds:**
  - the funder's research brief;
  - the NGO's Doc Vault;
  - the org, programme, partner-line and match rows;
  - the funder's form and public pages.
- **It reasons about what the funder wants,** compares that with what Sangam knows about the NGO, and finds what is missing.
- **It never fills a gap with an assumption.** It asks one targeted question at the moment a section needs it, never a questionnaire upfront.
- **It builds the proposal section by section.** The person reviews, corrects and approves every fact, and every fact keeps its source.
- **Code owns** the steps, the exit checks, the fact list, reliability, when a question may be asked, the trace check, the polish check and the .docx.
- **One deep agent** reads, reasons, asks and drafts inside those rules: the agent proposes, code checks.

## 2. Current implementation

**Proposals today are kept only in the browser.**
- `frontend/features/ask/views/proposals/store.ts` keeps them in `localStorage` (`sangam.proposals.v1`) with string UUID ids.
  - `useProposals` is used by `AskWorkspace.tsx`, `FunderMatchView.tsx`, `MatchCard.tsx`, `ProposalsView.tsx` and `ProposalShell.tsx`.
- `.../proposals/start.ts` builds G1/G2 from the saved match detail:
  - the `eligibility` criterion's note and cites;
  - the `not_judged` lines starting "The funder's own bar";
  - `earlier_phase` from the `relationship` points;
  - the first `documents` row with `doc_type=proposal_template`.
- `.../proposals/rubric.ts` holds the rubric as frontend data: `CORE` A1–A16, `F1`, `F4`, `MUST_SCORE_2 = A6/A15/F1`, `displayCodes` and `defaultStyle`.
- `ProposalShell.tsx` has three steps: gates, template/documents/style, and a sections stub.

**Database**
- `db/migrations/0009_proposals.sql` created `proposals` with `org_id`, `funder_id`, `template_id`, `title`, `status`, `requested_amount`, `thread_id → threads`, `draft_document_id`, `fit_score_id` and `created_by`. There are no `work` or `summary` columns.
- `0031` re-pointed `template_id` to `documents`, and `0034` dropped `grant_id`.
- RLS in `0027_rls.sql`:
  - `proposals_read` allows `my_org_ids()` or staff;
  - `proposals_insert` and `proposals_update` allow only `my_writable_org_ids()`, so neither staff nor stewards can write;
  - `documents_insert` allows `my_writable_org_ids()` or staff.
- The last migration is `0047_document_links.sql`, so the next is **0048**.
- `threads` (`0005`) already has `use_case IN ('ask','proposal',…)`, `org_id` and `visibility IN ('private','team','team_and_stewards')`. `app.can_open_thread` (`0024`) honours `team_and_stewards`.

**Saved Funder Match runs**
- `0042_funder_matches.sql` holds them. They are read through `backend/app/repositories/funder_matches.py` (`latest_run`, `get_detail`).

**Uploads**
- `backend/app/api/routes/documents.py` (`create_upload_url`, `confirm_upload`) calls `repo.org_id_for_member(..., write=True)`, which excludes stewards.
- `_extract` reads PDFs only.

**Agent platform**
- `backend/app/core/lifespan.py`:
  - `AGENT_NAMES = {"/agent","/ingest"}`;
  - `_build_agents` builds the graphs on the first chat turn;
  - `_add_agent_route` puts `Depends(chat_access)` on every path.
- `backend/app/core/security.py`: `chat_access` → `_own_thread` → `threads.claim_thread` returns 404 to anyone but the first claimer or staff. It sets `chat_scope` to a `CallerScope`.
- `backend/app/agent/harness.py` provides `install()` and `filesystem(backend, keep=…, evict=…)`.
- `backend/app/ingest/agent.py` is the template:
  - isolated subagents, each with its own `filesystem_tools(...)`, `RunSources()` and `fallback(...)`;
  - `INTERRUPT_ON` with `ask_for_sources`.
- `backend/app/ingest/middleware.py` has `ChosenSources`, `RunSources`, `TickedSources`, `SaveRefusal`, `research_rubric`, `cheap_summarizer` and `call_limit`. `run_sources.py` has the tool-name sets.
- Tools to reuse:
  - `ingest/tools/research_tools.py`: `search_public_sources`, `read_page`, `fetch_document`, `read_document_pages`;
  - `ingest/tools/vault_tools.py`: `list_vault_documents`, `read_vault_document`;
  - `ingest/tools/pipeline_tools.py::choose_sources`.
- `backend/app/ingest/vault.py::read` handles PDF and .xlsx, with markers like `[vault:<id>#p<n>]`.
- `backend/app/ingest/brief.py`: `record(markdown)` returns (facts, unplaced), and `_strength` orders sources by evidence tier, then confidence.
- `backend/app/ingest/research_records.py::FindingBase` requires `evidence` of at least 20 characters and an http(s) `source_url`. `Money`/`to_inr` are the one place units are converted.
- `backend/app/repositories/profile_facts.py::org_facts` returns typed org facts, public rows only.
- Frontend:
  - `frontend/app/api/copilotkit/[[...slug]]/route.ts` registers the agents (`maxDuration = 1800`);
  - `frontend/lib/useAgentChat.ts` is the chat hook;
  - `frontend/features/ingest/components/SourcesCard.tsx` is the `useInterrupt` → `resolve({decisions})` pattern.
- `proposals` is in the SQL catalog's `KNOWN_EXCLUDED`.

## 3. Proposed approach

**A third deep agent, `/proposal`.** It is built like `ingest/agent.py`: `create_deep_agent`, `install_harness()`, `filesystem(...)` on the supervisor and every subagent, and `fallback` tiers.

**Six steps, owned by code.** The current step is in `work.stage`. `app/proposals/steps.py::exit_check(stage, work) -> list[str]` returns what is missing. Both the agent's `advance_step` and REST `POST /api/proposals/{id}/advance` call it. A `StageGate` middleware refuses tools that do not belong to the current step.

| Step | Gathered automatically | Exit check (code) |
|---|---|---|
| 1 Can you apply? | G1/G2 from the saved match (`start.ts` logic moved server-side) | both gates answered |
| 2 What the funder wants | sources picked first; then `funder-reader` reads the brief, site, CSR report and form | sources set, priorities confirmed, template set or skipped |
| 3 Your pitch | programmes, `program_tags`, partner lines, `document_links`, the match's theme note naming a programme | programme, amount, style set by the person |
| 4 Write | per section, `evidence-reader` reads the picked Doc Vault files and the org brief | every planned section has text and a score |
| 5 Review | the facts view, the contradiction check, readiness | ready, or the list of what is missing |
| 6 Finish | assemble, polish, .docx | a version saved |

**The agent proposes, code checks.** Every write tool validates and returns `REFUSED: …`, never raises:
- `add_facts`: the source is verified for its kind;
- `ask_user`: the reason to ask must be warranted by the fact list;
- `write_section`: trace check, then grade, then `rev`;
- `flag_conflict`: both facts exist and are of equal tier.

**Architecture**

```
 Browser · Ask → Proposals → one proposal
 ┌─────────────────────────────────────────────────────────────┐
 │ step rail │ step card (facts · question · draft) │ Tell Sangam│
 └────┬──────────────────┬─────────────────────────────┬───────┘
      │ REST             │ interrupt answers           │ chat
      ▼                  ▼                             ▼
 ┌──────────────┐   ┌────────────────────────────────────────────────┐
 │ /api/        │   │ /proposal · thread proposal-<id> · shared      │
 │ proposals    │   │  SUPERVISOR (MODEL)                            │
 │ route→repo→  │   │   reads:  read_proposal · read_org_record ·    │
 │ schema       │   │           read_match                           │
 └──────┬───────┘   │   pauses: choose_sources · ask_user  ◄─ HITL   │
        │           │   writes: add_facts · write_section ·          │
        │           │           flag_conflict · advance_step         │
        │           │      every write passes CODE CHECKS:           │
        │           │      steps · reliability · questions · trace · │
        │           │      grade · rubric                            │
        │           │      task(...) gated by RunSources             │
        │           │  ┌────────────────┐  ┌──────────────────┐      │
        │           │  │ funder-reader  │  │ evidence-reader  │      │
        │           │  │ RESEARCH_MODEL │  │ RESEARCH_MODEL   │      │
        │           │  │ web + brief +  │  │ Doc Vault + org  │      │
        │           │  │ template       │  │ brief, no web    │      │
        │           │  └────────────────┘  └──────────────────┘      │
        │           └──────────────┬─────────────────────────────────┘
        ▼                          ▼
 Postgres: proposals.work {stage, gates, sources, funder, pitch, facts[], sections, conflicts, versions}
           funder_matches · programs · funder_activity · document_links · documents
 Storage:  source-archive/entities/<slug>.md (briefs, read-only) · org-vault/<org>/proposals/<id>/vN.docx
```

**One turn, worked through (step 4, section A11 "Track record"):**
1. The supervisor sends the `evidence-reader` for facts for A11. `RunSources` lets it read only the picked Doc Vault files.
2. It returns "24,765 families, 2019–22 [activity:41]" and "no 2025-26 outcome found". `add_facts` stores k15, which is green because it is registry data.
3. The supervisor calls `ask_user(reason="missing_required", section="A11")`. Code confirms that A11 has no outcome from the last 24 months, and the card appears.
4. The person answers "1,150 households, 9 → 10.5 food-secure months". It is stored as k16, "you said".
5. The supervisor calls `write_section("A11", "…24,765 families ⟦k15⟧ … 1,150 households ⟦k16⟧")`. The trace check passes, and the section is graded 2 of 2.
   - Had the draft said "1,200", it would be refused, and the error would name the untraced number.

**The fact list (`work.facts[]`, no new table).**
- `ProposalFact` reuses FindingBase's fields: `evidence`, `source_url`, `source_name`, `confidence`, `basis`, `page`.
- It does not subclass FindingBase, because a registry fact has a marker (`[org:3]`) and no http URL.
- It adds:
  - `id`, `kind`, `subject`, `value`, `marker`, `as_of`;
  - `tier`;
  - `status`: proposed / confirmed / corrected / rejected;
  - `used_in`, `supersedes`;
  - `origin`: registry / vault / web / you_said / derived;
  - `private`.
- Sections cite facts as ⟦k7⟧.

**Reliability in code** (`app/proposals/reliability.py`).
- The colour comes from the origin:
  - registry or quoted Doc Vault page: green;
  - web: amber;
  - "you said": its own colour;
  - derived by the agent: amber until confirmed.
- Then freshness by kind:
  - registrations: until expiry;
  - financials: the last FY;
  - outcomes and baselines: 24 months;
  - staff: 6 months.
- Corroboration raises a fact one colour. Ties use brief's `_strength` order.
- *Example:* sesta.org's "120 villages" is amber. If the 2024-25 annual report says 120 on p.14, the fact becomes green.

**What it is tracking lives in the proposal row, not the conversation.** Sources chosen, the open question and confirmed priorities are kept in `work`, because a proposal chat spans days and `cheap_summarizer` drops old tool messages.

**Steps 5 and 6 are mostly code.** Correction propagation, the equal-tier contradiction check, readiness, the polish check and the .docx are deterministic. Polish is one `Settings.model` call made by a REST route.

**Alternatives considered and rejected**
- **An agent per section:** costs too much and splits the fact list.
- **A `proposal_facts` table:** "no new tables" was already decided.
- **Grading with `RubricMiddleware`:** it grades only at the end of a run.
- **Copying the Import tools:** they are imported, so `run_sources`' name sets and `test_every_tool_defined_is_also_registered` still hold.

## 4. Decisions taken (14 Oct)

1. **One shared chat per proposal.** The thread is created by REST with `use_case='proposal'` and `visibility='team_and_stewards'`.
   - A new `proposal_chat_access` opens it with `can_open` and never claims it.
   - So SeSTA's admin and steward share `proposal-42`, and it stays out of Ask's Recent Chats.
2. **No saved Funder Match run means no proposal.** `POST /api/proposals` returns 409 "run Funder Match first". The gates have one source, the saved run.
3. **Public org rows plus the Doc Vault.** `read_org_record` uses `org_facts` (public only). Private details come from the vault reader and the person's answers.
4. **Typing in the drawer while a question is open answers it.** The text resumes the pending `ask_user` interrupt, and the agent may still pick answers to other open slots out of it.
5. **Each section is graded inside `write_section`.** A6, A15 and F1 get one allowed rewrite when they score below 2.
6. **An uploaded funder form gets its own tool.** `read_template()` is bound to `proposals.template_id`, because the funder-reader has no Doc Vault tools.
7. **`fit_score_id` stays on `proposals`, unused.**
8. **Word files in the Doc Vault are read by paragraph.** `vault.read` cites them as `[vault:<id>#para<N>]`.
9. **Storage code F4** for "Earlier phase", shown as F2 by `displayCodes`.
10. **Confirmed facts do not write back** to the org's record or brief in v1. Private (vault) facts never leave the proposal.

## 5. Implementation steps (one PR each)

### M1: storage, REST resource, uploads, the list on the API

**Goal:** proposals live on the server; stewards and staff can write; Word and Excel uploads become readable; the browser store goes.

**Files**
- New: `db/migrations/0048_proposal_work.sql`.
- New backend: `backend/app/proposals/{__init__,rubric,readiness,gates,work}.py`, and `api/routes/proposals.py`, `repositories/proposals.py`, `schemas/proposals.py`.
- Edited backend: `api/router.py`, `api/routes/documents.py`, `repositories/documents.py` (docstring), `ingest/vault.py`, `pyproject.toml`.
- Frontend: `frontend/features/ask/views/proposals/*` (`store.ts` becomes `api.ts`, `start.ts` is deleted), plus `ProposalsView.tsx`, `AskWorkspace.tsx`, `FunderMatchView.tsx` and `MatchCard.tsx`.

**Changes**
- **0048:**
  - `proposals` gains `work` and `summary` jsonb (`NOT NULL DEFAULT '{}'`).
  - `proposals_insert`, `proposals_update` and `documents_insert` become `org_id IN (SELECT app.my_org_ids()) OR (SELECT app.is_staff())`.
  - Keep the 0027 `DO` guard.
- **`rubric.py`:** the rubric moves server-side (`proposal-v2`).
  - `DEPENDS_ON`: A2/A3 before A4, A4 before A5/A6, A5 before A15, everything before A1.
  - `sections_for(earlier_phase, template)` adds T sections and overlays.
- **`readiness.py`:** `summary(work)` in the 9 Oct shape, plus `stage`, `facts_open` and `questions_open`.
- **`gates.py`:** ports `start.ts`, using `latest_run` and `get_detail`.
- **`work.py`:**
  - `ALLOWED_PATHS` covers gates, template, style, stage, `sections.<code>.text|done` and `facts.<id>.status|value`.
  - `apply()` runs `SELECT … FOR UPDATE`, then `jsonb_set` per path, then the section-`rev` 409, then recomputes `summary`.
  - The agent tools use the same function.
- **REST routes:** `GET /api/proposals?org&funder`, `POST /api/proposals`, `GET /{id}`, `PATCH /{id}`, `PATCH /{id}/work`, `POST /{id}/advance`. All `require_user`, on the caller pool.
  - POST, in one transaction: inserts the proposal at stage 1, creates thread `proposal-<id>` (decision 1), and sets `proposals.thread_id`.
  - It returns 409 without a saved match (decision 2).
- **Uploads:**
  - both upload routes switch to `write=False`;
  - `_extract` gains `.docx` (python-docx: paragraphs and tables) and `.xlsx` (openpyxl, capped);
  - `vault.read` gains `.docx` (decision 8).
- **Dependency:** `python-docx`.
- **Frontend:**
  - an API hook replaces `useProposals`, and ids become numbers;
  - `MatchCard` calls POST;
  - proposals saved in the browser are not migrated, and a one-line notice shows if any exist.

**Validation**
- `make migrate`.
- `psql` as member, steward, staff and stranger.
- `curl` the create, PATCH and 409 cases.
- A SeSTA workplan in .docx gets `content_md`.
- `npm run build`.

**Exit gate:** SeSTA's steward starts "SeSTA: women's farm enterprises, Baksa → ABF" from the Match card, ticks both gates, and sees it on another device.

### M2: agent skeleton, route, step 1 and the sources card, chat drawer

**Goal:** a `/proposal` agent that knows which proposal it is in, is shared by the team, and advances only through code.

**Files**
- New: `backend/app/proposals/{agent.py,instructions.md,middleware.py,steps.py,context.py}`, `tools/{__init__,proposal_tools,record_tools}.py`.
- Edited: `core/lifespan.py`, `core/security.py`, `frontend/app/api/copilotkit/[[...slug]]/route.ts`.
- New frontend: `proposals/{StepRail,TellSangam}.tsx` and `toolLabels.ts`.

**Changes**
- **Lifespan:**
  - `AGENT_NAMES["/proposal"]="sangam_proposal"`;
  - `_build_agents` adds `proposal_graph` with `SessionScopedAGUIAgent(..., emit_raw_events=False)`;
  - `_add_agent_route(app, path, access=chat_access)`, with `/proposal` passing `proposal_chat_access` (decision 1).
- **Binding to the proposal:** `context.current()` loads the proposal by thread id on the owner pool and refuses unless the caller is staff or a member of the proposal's org. Tools never take a proposal id from the model.
- **Supervisor tools:**
  - `read_proposal()`;
  - `read_match()`, cited `[score:N]`;
  - `read_org_record()`, cited `[org:N]` and `[activity:N]`;
  - `advance_step()`;
  - `choose_sources`, imported from Import.
- **Middleware:**
  - `ProposalSources` replaces `ChosenSources`. It reads `work.sources`, not the messages, and pins `vault_org` to the proposal's org.
  - `StageGate`.
  - `CallerNote`, `cheap_summarizer`, `clear_old_tool_results` and `fallback`, as in Import.
- **Interrupts:** `INTERRUPT_ON = {"choose_sources": …}`.
- **Frontend:**
  - `route.ts` registers `sangam_proposal`;
  - `ProposalShell` becomes a six-step rail;
  - the drawer uses `useAgentChat`, with history from `GET /api/proposals/{id}/messages` (reusing `saved_messages(graph_name="proposal_graph")`);
  - `choose_sources` reuses the `SourcesCard` pattern.

**Validation**
- SeSTA's admin and steward open the same thread, and a stranger gets 404.
- "Write A3" at step 1 is refused.
- One answer's SSE payload is about 100 KB, not about 1.7 MB.

**Exit gate:** step 1 → 2 happens only after both gates are ticked. The sources answer survives a forced summary.

### M3: facts, asking, the two readers, steps 2 and 3

**Goal:** what ABF wants and what SeSTA has become facts in the list, and questions are asked by rule.

**Files**
- New: `backend/app/proposals/{facts,reliability,questions,records}.py`, `tools/{ledger_tools,reading_tools}.py`, `prompts/{funder_reader,evidence_reader}.md`.
- New frontend: `QuestionCard.tsx`, `FunderWantsCard.tsx`, `PitchCard.tsx`.

**Changes**
- **`add_facts`** verifies each fact by its origin:
  - registry: the marker's row is re-read with fixed SQL and the value must appear in it;
  - vault: `vault.check_findings` against the picked documents;
  - web: an http URL and evidence of at least 20 characters;
  - you_said: the quote must appear in one of this thread's human messages;
  - derived: it cites `from=[k…]` and stays amber.
  - Tier and colour are set by `reliability.py`.
- **`read_brief(entity)`** resolves `entity_research.resolved_funder_id` / `resolved_org_id` before the catalog slug, and returns `brief.record()` facts.
- **`read_template()`** (decision 6).
- **`funder-reader`** (`RESEARCH_MODEL`, isolated):
  - tools: `read_page`, `search_public_sources`, `fetch_document`, `read_document_pages`, `read_brief`, `read_template`, `add_facts`;
  - middleware: `filesystem(backend)`, `RunSources()`, `fallback`;
  - returns `FunderWants`: priorities, themes, places, terminology, past grants, template sections, limits and form.
- **`evidence-reader`** (`RESEARCH_MODEL`, isolated):
  - tools: `list_vault_documents`, `read_vault_document`, `read_brief`, `add_facts`;
  - middleware: `filesystem(backend, evict=False)`, `RunSources()`, `DropFilesOnExit()`, `fallback`;
  - no web tools, and nothing written to `vault_research`.
- **`ask_user`** is an interrupt whose `reason` is one of the six below.
  - `AskGate` (the `ChosenSources` pattern) refuses unless `questions.warranted(...)` holds, no other question is open, and the section is the current one.
  - The answer becomes a you_said fact. Text typed in the drawer resumes the interrupt (decision 4).

| Reason to ask | Code check | SeSTA → ABF example |
|---|---|---|
| Missing element | A required Strong element has no fact | A6 needs a baseline; there is "412 SHGs" but no survey figure |
| Disagreement | Same kind, subject and period at equal tier, different values | sesta.org: 120 villages; the 2024-25 report: 96 |
| Stale | Older than its kind's window | "Income up 38%" is from FY2021-22 |
| Weak support | A6, A15 or F1 rests only on amber facts | A15's "₹8,500 per household" comes only from a web page |
| Org's call | The kind is programme, amount or gate | Baksa farm enterprises or Udalguri SHG federations? |
| Would infer a number | The draft needs a number no fact gives | ABF's ceiling is ₹5 crore, but SeSTA has no requested amount (no suggestion offered) |

- **Question shape:** found → missing → why the funder cares → suggestion.
  - *Example:* "Found 412 SHGs [k12] in your 2024-25 report p.14. Missing: an outcome for the last 12 months. ABF scores A6 on outcomes, not counts. Suggestion: the March 2026 household survey, if you have it."
- **Exit checks in `steps.py`:**
  - step 2: sources, funder and confirmed priorities are set, and the template is set or skipped;
  - step 3: programme, amount and style are set by the person.

**Validation:** SeSTA → ABF on local with a seeded ABF brief and two Doc Vault PDFs. No Doc Vault text appears in the funder-reader's trace, and an `ask_user` with no warrant is refused.

**Exit gate:** ABF's priorities and SeSTA's pitch are confirmed, and every fact shown has a colour and a source.

### M4: writing section by section

**Goal:** sections drafted in dependency order, each traced to cited facts and scored 0–2.

**Files**
- New: `backend/app/proposals/{trace,grade}.py`, `prompts/section_grade.md`. `write_section` is added to `ledger_tools.py`.
- New frontend: `WriteCard.tsx`.

**Changes**
- **`write_section(code, text, cites, rev)`**
  - **Trace check** (`trace.py`, shared with polish):
    - numbers, %, lakh and crore normalised through `Money`/`to_inr`;
    - places matched against `geography.py` and `locations`;
    - org, funder and partner names in the fact list.
    - Each must appear in the value or evidence of a fact cited in the same paragraph.
    - *Example:* "60 villages in Baksa" with only ⟦k4⟧ = "96 villages" is refused.
  - **Grade:** one `UTILITY_MODEL` call returns `{covered, missing}`. None missing scores 2, one missing scores 1, more scores 0 (decision 5).
  - On save: `rev+1`, `used_in` is set on the cited facts, and `[Add: …]` remains where nothing supports the text.
- **Order:** `StageGate` allows `write_section` only for the next section in `DEPENDS_ON` order, or one the person picked.

**Validation:** SeSTA's A3 is refused once for an untraced "62%", then saved. A1 is written last.

**Exit gate:** a full draft where every number cites a fact.

### M5: review

**Goal:** the person checks every fact, a correction reaches every section that uses it, and readiness is computed.

**Files**
- New: `backend/app/proposals/review.py`; routes `POST /{id}/facts/confirm` and `POST /{id}/facts/{k}/correct`.
- New frontend: `ReviewCard.tsx`.

**Changes**
- **Facts view:** grouped by colour, with "Confirm all".
- **Correct:**
  - it creates a you_said fact with `supersedes=k` and sets the old one to `corrected`;
  - where the old value appears verbatim in a sentence that cites k, code replaces it;
  - otherwise the section is marked `needs_rewrite` and goes back through `write_section`.
  - *Example:* villages corrected from 120 to 96 fixes A2 and A1 in place, and A4's "reach all 120" is flagged for a rewrite.
- **Contradiction pass:** code first, over equal-tier facts. Then the agent's `flag_conflict` for clashes in meaning, such as a "3-year project" against a 24-month workplan.
- **Ready:**
  - both gates;
  - no core section at 0;
  - A6, A15 and F1 at 2;
  - overlays met;
  - no used fact still `proposed`;
  - no open conflict.

**Exit gate:** "Ready", or the exact list of what is missing.

### M6: finish

**Goal:** assemble, a checked polish, a .docx in the Doc Vault, and versions.

**Files**
- New: `backend/app/proposals/{polish,assemble}.py`, `prompts/polish.md`; routes `POST /{id}/polish` and `POST /{id}/versions`.
- New frontend: `FinishCard.tsx`.

**Changes**
- **Polish:** one `Settings.model` call. `trace.extract` runs before and after.
  - Any number, place or name added, dropped or changed refuses the polish and shows the difference.
  - The result is stored with a hash of the sections, which drives the stale banner.
- **.docx:** built from `work.polished` (title, funder and date, headings, highlighted `[Add:]` gaps).
  - Stored at `<org_id>/proposals/<id>/v<N>.docx`.
  - A `documents` row with `doc_type 'proposal_draft'` and `is_ai_generated`, inserted on the caller pool.
  - `work.versions[]` gets `{n, document_id, at, by, facts_snapshot}`.

**Validation:** a polish that turns "₹4.2 crore" into "₹42 lakh" is refused. v2 keeps v1. A steward can save a version.

**Exit gate:** SeSTA downloads v1.docx from the Doc Vault, with its facts snapshot.

**Every PR, M1–M6**
- Run `make wiki-update` and add a CHANGELOG line.
- Edit `docs/ARCHITECTURE.md` where a rule changes:
  - M1: "a steward never writes", and "proposals live in localStorage";
  - M2: "two agents".
- Root `CLAUDE.md` gets 0048 and the third agent.
- Frontend PRs sync the design system (`docs/DESIGN_SYSTEM.md`).

## 6. Test plan

No new tests. These existing tests must stay green:

| Test | Why it matters here |
|---|---|
| `tests/test_ingest.py::test_every_tool_defined_is_also_registered` | Green only if the Import tools are imported, not redefined |
| `tests/test_ingest.py` prompt/instructions tests | Import only; confirm unchanged |
| `tests/test_harness.py` | Builds Ask and Import only; check by hand that the proposal subagents carry only `read_file` |
| `tests/test_import_threads.py::test_thread_listing_sql_is_fixed_per_kind` | Proposal threads are `use_case='proposal'`, so the listing is unchanged |
| `tests/test_vault.py` | The upload fake ignores `write`; confirm |
| `tests/test_rls.py::test_a_proposal_reaches_only_the_org_and_staff` | The read policy is unchanged after 0048 |
| `tests/test_sql_catalog.py` | `proposals` stays in `KNOWN_EXCLUDED` |
| `tests/test_tracing.py::test_every_documented_variable_reaches_the_container` | Add no Settings variable |

- **Integration:** `pytest -m integration` after `make migrate` on a fresh database.
- **Manual:** member, admin, steward, staff and stranger, at every step.
  - Reopen at each step.
  - Two people editing different sections (no clash) and the same section (409).
  - Phone width.
  - `npm run lint && npm run build` and `ruff check .`.
- **Evals:** `make evals TAG=canary` before and after M2, to show Ask is unaffected. One SeSTA → ABF run on local, with its cost recorded in Langfuse (`sangam_proposal`).

## 7. Risks and edge cases

| Risk | Example and mitigation |
|---|---|
| First-turn latency | Three graphs compile on the first chat turn. Measure "Agents built on first use"; split loading per graph if it passes ~1 s |
| Owner-pool tools skip RLS | A steward of two NGOs must not reach `proposal-43` by guessing. `context.current()` is the guard |
| Doc Vault text reaching web context | SeSTA's salary sheet must never reach the funder-reader. The evidence-reader has no web tools, and `DropFilesOnExit` cleans up |
| `work` size | ~200 facts plus 19 sections is about 150–200 KB, rewritten on each write. The list reads only `summary` |
| Trace false positives | "FY2024-25" and "Schedule VII" read as numbers. Exempt fiscal-year patterns and taxonomy codes |
| Polish refusal loop | Rewording lakh as crore is refused on purpose, and the polish prompt says so |
| Cost | Two research subagents and one Opus turn per section. Measure on the first three proposals |
| Saved .docx in Scout's Doc Vault list | "v1.docx" shows up for Scout's vault-reader. Documented, not fixed |
| Long turns | Several sections in one turn approach 1800 s. One section per turn unless the person asks |

## 8. Acceptance criteria

1. A steward or staff member starts two SeSTA → ABF proposals. Both appear in the list on any device.
2. A stranger gets 404 on the proposal, its messages and its thread. A member can read and write.
3. Step N+1 opens only when step N's exit check passes. Reopening an earlier step keeps later work.
4. Sources are picked before any read. A read outside them is refused, even days later after the chat was summarised.
5. Every fact shown has a colour, a source and a status.
6. At most one question is open. It names its reason and follows found → missing → why → suggestion, with no suggestion for an inferred number.
7. A question with no warranting gap is refused.
8. A section with an untraced number, place or name is refused. Saved sections cite ⟦k⟧ and carry a score from 0 to 2.
9. Correcting a fact updates or flags every section that used it. Ready requires every used fact to be confirmed or corrected.
10. A polish that changes any number, place or name is refused.
11. Each version is a .docx in the Doc Vault with a facts snapshot, and earlier versions stay.
12. Doc Vault facts never appear in a brief, in `entity_research` or `vault_research`, or in the funder-reader's context.
13. Ask and Scout are unchanged: canary evals pass and Recent Chats is unchanged.

## 9. Files expected to change

| File | Change | Reason |
|---|---|---|
| `db/migrations/0048_proposal_work.sql` | new | `work`/`summary`; insert and update policies |
| `backend/app/proposals/*.py` | new | Code-owned steps and checks |
| `backend/app/proposals/{agent.py,instructions.md,middleware.py,prompts/}` | new | Deep agent, subagents, StageGate, ProposalSources, AskGate |
| `backend/app/proposals/tools/*.py` | new | The agent's tools |
| `backend/app/api/routes/proposals.py`, `repositories/proposals.py`, `schemas/proposals.py` | new | REST resource |
| `backend/app/api/router.py` | edit | Mount proposals |
| `backend/app/api/routes/documents.py`, `repositories/documents.py` | edit | `write=False`; .docx/.xlsx text |
| `backend/app/ingest/vault.py` | edit | .docx read by paragraph |
| `backend/app/core/lifespan.py`, `core/security.py` | edit | `/proposal`, `proposal_chat_access` |
| `backend/pyproject.toml` | edit | `python-docx` |
| `frontend/app/api/copilotkit/[[...slug]]/route.ts` | edit | `sangam_proposal` |
| `frontend/features/ask/views/proposals/*` and their callers | edit/new | API store, step rail, cards, drawer |
| `frontend/app/globals.css` | edit | `.pr-*` classes, design system first |
| `docs/ARCHITECTURE.md`, `CLAUDE.md`, `docs/CHANGELOG.md`, `openwiki/**` | edit | Rules, facts, changelog, wiki |

## 10. Order of work

- [ ] M1: 0048, the REST resource, uploads, the list on the API. Exit: shared across devices.
- [ ] M2: `/proposal`, shared chat access, agent skeleton, sources kept in `work`, drawer. Exit: admin and steward share a thread.
- [ ] M3: facts, reliability, `ask_user` with AskGate, the two readers, steps 2–3. Exit: priorities and pitch confirmed.
- [ ] M4: `write_section`, trace, grade, order. Exit: a fully traced draft.
- [ ] M5: review, propagation, conflicts, ready. Exit: Ready or the exact list.
- [ ] M6: checked polish, .docx, versions. Exit: v1.docx in the Doc Vault.
- [ ] Each PR: `make wiki-update`, a CHANGELOG line, ARCHITECTURE and CLAUDE.md where rules change, a design-system sync, `npm run build`, `ruff check .`, `pytest`, and `pytest -m integration`.
