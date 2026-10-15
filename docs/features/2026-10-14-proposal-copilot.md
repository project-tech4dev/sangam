# Proposal Copilot: a human-in-the-loop agent that builds a proposal with the NGO

Draft v3 · 2026-10-15 · first version trimmed · branch `feat/proposal-copilot`

**Replaces** the 9 Oct proposals spec (`features-plans/proposals/2026-10-09-proposals-design.md` on
`docs/proposals-spec`, never merged). These parts of that spec carry over unchanged:

- gates G1/G2;
- template and writing style;
- rubric `proposal-v2` with A/B/C/F display codes;
- assemble → polish → .docx with versions;
- PATCH `work` by path with a section `rev`;
- several proposals per org and funder;
- the org's admins, its stewards and staff start and write a proposal; members read it and do not edit it.

What it replaces is "draft every section at once with ~20 fixed calls". **The steps are the Funder Match prototype's**
(https://claude.ai/artifact/H1b4nv5ReQn8mvHg2HhPB5): 1 Eligibility gates → 2 Template, documents and style → 3 Proposal,
then Assemble → Polish → Save. **The screens are the Claude Design canvas** (https://claude.ai/artifact/Vhy3vqLJPs43rKpeNCFydr),
reviewed for NGO staff who are not technical. Every path below was checked against `origin/master` at
`5c63bb4`. The running example is SeSTA (the NGO) writing to Axis Bank Foundation (ABF, the funder).

## 1. Requirement summary

- Once an NGO is matched with a funder, an agent guides them to a strong proposal for that funder. It is not a one-shot generator.
- **It reads what Sangam already holds:**
  - the funder's research brief;
  - the NGO's Doc Vault;
  - the org, programme, partner-line and match rows;
  - what Sangam already holds about the funder: its brief, archived documents and past grants. No web research.
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

**Three steps, owned by code.** The current step is in `work.stage`. `app/proposals/steps.py::exit_check(stage, work) -> list[str]` returns what is missing. Both the agent's `advance_step` and REST `POST /api/proposals/{id}/advance` call it. A `StageGate` middleware refuses tools that do not belong to the current step. A "How this works" screen comes first, once.

| Step (on screen) | What happens | Exit check (code) |
|---|---|---|
| 1 Can you apply? | Each funder requirement shows the rule and what Sangam has on record. The person answers *Yes, we have it* · *We'll have it before sending* · *No*. No uploads | every gate answered. *No* on a hard gate stops the proposal; answers stay saved |
| 2 Your documents and style | **Funder form:** used if Sangam holds it, else a link or an upload (Axis), or "use Sangam's usual order". **Documents:** upload to the Doc Vault and tick what Sangam may read (impact assessments, evaluations, outside studies, annual reports, workplans, budgets, baselines). **Writing style:** the default, editable. The ticks are `work.sources` | form set or skipped; style set; "Write the first draft" pressed |
| 3 Write the proposal | Readers run, every section is drafted with a marked gap wherever nothing supports it, then one question at a time closes the gaps | ready (M5), or the list of what is missing |
| Before you send it | Assemble; smooth the language (checked); download as Word, or save a copy | a version saved |

**Step 3's five tabs.** Rubric codes and scoring stay `proposal-v2`; only the grouping changes. The prototype's four tabs
(the case and the plan, people, durability and money, this funder) become five by splitting the first.

| Tab | Sections (storage code) |
|---|---|
| **The Idea**: what is this all about? | Past studies (facts) · Context A2 · Problem and baseline A3 · Objectives and results A4 · Summary A1, written last |
| **Your Project**: how will we do it? | Workplan by quarter A5 · Measuring results A6 · Learning A7 · the funder form's own questions (ABF §6, convergence with government) |
| **The People**: who will do it? | Community participation A8 · Inclusion A9 · Team A10 · Track record A11 · Partnerships A12 |
| **The Ask and Risk**: how much, and what could stop it? | Budget A15 · Other funding A16 · Risks A13 · After the grant A14 |
| **Why me and you** | Fit with the funder's goals F1 · Earlier phase results F4 |

- **Past studies open The Idea.** The evidence readers pull findings from impact assessments, evaluations and outside
  studies into the fact list; A3, A4 and A11 cite them. A list of facts, not a scored section, so A1–A16 and readiness are unchanged.
  - *Example:* "Impact assessment 2023: federation credit added 2 food-secure months a year (page 12)" is k9; A4's "from 9 to 11 months" cites it.
  - Outside studies come only from step 2's files and documents Sangam archived. One nobody uploaded is not found, and the tab says so.
- **Hints are the rubric's** (`rubric.ts`, from Preetisha's templates): the question, a strong answer's elements ticking off,
  what a weak answer looks like, and "Score 1 of 2" with the key "2 = strong, 1 = one thing missing, 0 = not usable yet".
  A1's elements run problem → place → objective → results with numbers → the ask, so the summary leads with impact.
- **Programme and amount are not a step.** The programme is the proposal's title at creation. The amount is asked as the
  org's call when A15 or A1 first needs it.

**Plain language on screen.** The person never sees a storage code or marker: no A3, G1, k9, `vault:41#p12`, `score:212`,
"core 18 / 32" or "Doc Vault". Sections show their names, sources show in words ("Impact assessment 2023, page 12"), and
each fact shows its standing in words as well as colour ("✓ From your document", "! From the web, not checked"). The codes
stay in `work` and in the agent's context. The agent's prompt carries the same rule for its chat text.

**The agent proposes, code checks.** Every write tool validates and returns `REFUSED: …`, never raises:
- `add_facts`: the source is verified for its kind;
- `ask_user`: the reason to ask must be warranted by the fact list;
- `write_section`: trace check, then grade, then `rev`.

**Architecture**

```
 Browser · Proposals → one proposal
 ┌──────────────────────────────────────────────────────────────┐
 │ 3 steps │ step 3: 5 tabs · part (hints · facts · draft) │ chat │
 └────┬───────────────────┬─────────────────────────────┬───────┘
      │ REST              │ question answers            │ chat
      ▼                   ▼                             ▼
 ┌──────────────┐   ┌─────────────────────────────────────────────────┐
 │ /api/        │   │ /proposal · thread proposal-<id>-<user> · own   │
 │ proposals    │   │  SUPERVISOR (MODEL)                             │
 │ route→repo→  │   │   reads:  read_proposal · read_org_record ·     │
 │ schema       │   │           read_match                            │
 └──────┬───────┘   │   pauses: ask_user  ◄─ HITL, one at a time      │
        │           │   writes: add_facts · write_section ·           │
        │           │           advance_step                          │
        │           │   every write passes CODE CHECKS: steps ·       │
        │           │   reliability · questions · trace · grade       │
        │           │   task(...) gated by ProposalSources            │
        │           │  ┌───────────────────┐ ┌──────────────────────┐ │
        │           │  │ funder-file-reader│ │ evidence-reader × N  │ │
        │           │  │ RESEARCH_MODEL    │ │ one per ticked file, │ │
        │           │  │ brief · archived  │ │ in parallel          │ │
        │           │  │ funder documents ·│ │ RESEARCH_MODEL       │ │
        │           │  │ past grants · form│ │ that file + org brief│ │
        │           │  └───────────────────┘ └──────────────────────┘ │
        │           │   neither has a web tool                        │
        │           └──────────────┬──────────────────────────────────┘
        ▼                          ▼
 Postgres: proposals.work {stage, gates, template, sources, style, facts[], sections, questions, readers, run, log[], versions}
           funder_matches · programs · funder_activity · document_links · documents
 Storage:  source-archive/entities/<slug>.md (briefs, read-only) · org-vault/<org>/proposals/<id>/vN.docx
```

**One turn, worked through (step 3, The People tab, A11 "Track record"):**
1. The evidence readers have already run, one per ticked file. `ProposalSources` let each read only its own file.
2. It returns "24,765 families, 2019–22 [activity:41]" and "no 2025-26 outcome found". `add_facts` stores k15, which is green because it is registry data.
3. The supervisor calls `ask_user(reason="missing_required", section="A11")`. Code confirms that A11's required outcome has no fact, and the card appears.
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
  - `private`;
  - `document_id` for a fact read from a file, so a re-read replaces only that file's facts.
- Sections cite facts as ⟦k7⟧.

**Reliability in code** (`app/proposals/reliability.py`).
- The colour comes from the origin:
  - registry or quoted Doc Vault page: green;
  - web: amber;
  - "you said": its own colour;
  - derived by the agent: amber until confirmed.
- The colour is the fact's tier; nothing else changes it. Every fact shows its year, so the person sees an old one.
- *Example:* sesta.org's "120 villages" is amber; "96 villages" from the 2024-25 annual report, p.14, is green.

**The context layer: the agent is told where it is on every model call, and never has to remember.**
`app/proposals/context.py` is pure code with two functions, `stable(work)` and `live(work, screen, since)`. It is split in
two because deepagents caches the system prompt (`AnthropicPromptCachingMiddleware`), and text there that changes after
every save would invalidate the cached prefix on each call. Its own `MemoryMiddleware` handles changing memory the same way:
a separate block with its own cache breakpoint.

| Block | What it says | Comes from | Where it goes | Changes |
|---|---|---|---|---|
| **Stable** | the proposal, org, funder and programme; the funder's confirmed priorities; the form's questions; gate answers; the writing style | `work` | appended to the system message by `ProposalContext`, ending on a `cache_control` breakpoint (Anthropic models only) | rarely: step 2 done, a priority confirmed, a gate answered |
| **Live** | where the proposal is (step, tab, parts finished, scores, readers done); what is on screen; what teammates changed (not in this chat); what is waiting; what it may do next | `work`, `summary`, the screen and `work.log[]`, read fresh each call | added by `ProposalContext` after the stable block's breakpoint, on that one model call only, so the chat history and the checkpoint never hold it | every call |

Each line of the live block has its own source and trust:

| Line | Comes from | Trusted for |
|---|---|---|
| Where the proposal is | `work` and `summary` | everything |
| What the person is looking at | the screen, through `useAgentContext` (as Scout sends its ticks) | focus only, never permission. A part code the server doesn't know is dropped |
| What teammates changed | `work.log[]`, appended by `work.apply()` with who, what and when; the latest entries by anyone but the caller. Never their chat | everything |
| What is waiting | the open question; facts not yet confirmed; parts flagged to rewrite | everything |
| What it may do next | `steps.py` and `DEPENDS_ON` | everything; the tools check again |

*Example*, SeSTA's steward opens the problem part after a colleague edited the budget yesterday.

Stable block (cached; unchanged since step 2):

```
Proposal 42: SeSTA → Axis Bank Foundation · programme: SHG federations, Udalguri
ABF's confirmed priorities: rural livelihoods through community institutions, North-East India; ₹1–5 crore over 3 years
Form: ABF proposal format 2026 · workplan by quarter · §6 convergence with government
Gates: 12A, 80G, standing: yes · CSR-1: will have it before sending · 2025-26 accounts: yes
Style: plain, specific English for a CSR programme officer; ₹ in lakh and crore; every figure with source and year
```

Live block (this call only):

```
Step 3 · 4 of 19 parts finished · readers done (5 files)
On screen: The Idea › The problem, with figures (score 1 of 2) · selected: "38% of the 1,240 households"
Changed by others: Ravi changed the budget total to ₹2.4 crore (yesterday 16:10); fact k5 marked "Don't use it"
Waiting: no open question · 3 facts not confirmed · "What will change" flagged to rewrite (uses the old total)
Next allowed: ask one question about this part, or rewrite "What will change"
```

- The details (fact values, section text) stay behind `read_proposal()`, so both blocks stay short however big `work` grows.
- Building them needs no model call.
- Each person's chat is private, so the log is the only way one agent learns what a teammate did.

**What it is tracking lives in the proposal row, not the conversation.** Sources chosen, the open question and confirmed priorities are kept in `work`, because a proposal chat spans days and `cheap_summarizer` drops old tool messages.

**Review and "Before you send it" are mostly code.** Correction propagation, readiness, the polish check and the .docx are deterministic. Polish is one `Settings.model` call made by a REST route.

**Alternatives considered and rejected**
- **An agent per section:** costs too much and splits the fact list.
- **A `proposal_facts` table:** "no new tables" was already decided.
- **Grading with `RubricMiddleware`:** it grades only at the end of a run.
- **Copying the Import tools:** they are imported, so `run_sources`' name sets and `test_every_tool_defined_is_also_registered` still hold.

## 4. Decisions taken (14 Oct)

1. **The proposal is shared; each person's chat is their own** (changed 15 Oct). SeSTA's steward works on proposal 42 in `proposal-42-<steward id>`, its admin in `proposal-42-<admin id>`, and neither sees the other's.
   - `proposal_chat_access` claims the caller's own thread like an Ask chat (`use_case='proposal'`, `visibility='private'`, the proposal's `org_id`), so another person's thread is 404. It stays out of Ask's Recent Chats.
   - A teammate's changes reach the agent through `work.log`, never through their chat.
   - The chat sits in the right-hand panel of step 1, as in the design canvas; members get no chat.
2. **No saved Funder Match run means no proposal.** `POST /api/proposals` returns 409 "run Funder Match first". The gates have one source, the saved run. An org admin can save that run themselves (`0042`'s `my_match_org_ids()` is admins and stewards).
3. **Public org rows plus the Doc Vault.** `read_org_record` uses `org_facts` (public only). Private details come from the vault reader and the person's answers.
4. **Typing while a question is open resumes it, and `ask_user` sorts the reply** into one of three kinds:
   - *an answer*: stored as a you_said fact; the question closes;
   - *a question back* ("What does ABF mean by convergence?"): answered from what Sangam holds; the question stays open and its card shows again under the reply;
   - *skip or later*: the question is parked in `work.questions` with the gap still marked, and comes back when that part is opened again or on "Before you send it".
   With no question open, a typed message is an ordinary turn: Sangam answers from the context layer and its read tools, names sources in words, says when it does not hold the answer, and changes the proposal only through the write tools.
5. **Each section is graded inside `write_section`.** A6, A15 and F1 get one allowed rewrite when they score below 2.
6. **An uploaded funder form gets its own tool.** `read_template()` is bound to `proposals.template_id`, because the funder-file reader has no Doc Vault tools.
7. **`fit_score_id` stays on `proposals`, unused.**
8. **Word files in the Doc Vault are read by paragraph.** `vault.read` cites them as `[vault:<id>#para<N>]`.
9. **Storage code F4** for "Earlier phase"; screens show section names, not codes.
10. **Confirmed facts do not write back** to the org's record or brief in v1. Private (vault) facts never leave the proposal.
11. **The funder side reads only what Sangam holds** (14 Oct review): the brief, archived documents linked to the funder,
    `funder_activity` and the form. No web tools on any reader.
12. **Gates are answered, not uploaded.** "We'll have it before sending" stays an open item on "Before you send it".
13. **No `choose_sources` interrupt.** Step 2's ticks are `work.sources`; `ask_user` is the one interrupt.
14. **Five tabs** in step 3 (above); rubric codes and scoring unchanged.
15. **Past studies are facts, not a scored section.**
16. **No storage code on screen** (above). The screens do not say who can read a document.
17. **A context layer on every model call, in two blocks.** One middleware, `ProposalContext` (as built in M2): a stable block in the system prompt ending on a cache breakpoint, then a live block after it, never saved. Both are built by code from `work`, the screen and `work.log`.
18. **Tests for the code-only safeguards** (15 Oct): each milestone tests its own; no tests of model output and no evals. An exception to "no new tests in a PR" for this feature.
19. **M3 is two PRs:** facts and asking (M3a), then the readers and step 2 (M3b).
20. **No run lock** (changed 15 Oct). Two people may chat at once; clashing saves are refused by `work.apply`'s row lock and section `rev` (409).
21. **Web facts come only from Import's briefs**; no proposal reader searches the web.
22. **A trimmed first version** (15 Oct): colour by source only, three reasons to ask, no meaning-clash tool, no changed-file check, a polish check on numbers, places and names only, the form's questions without its limits, no staff numbers. Each is in "Later".
23. **The agent is called Sangam Pitch on screen** (15 Oct). The route, threads and code keep "proposal", as Scout's keep "ingest".

## 5. Implementation steps (one PR each)

### M1: storage, REST resource, uploads, the list on the API

**Goal:** proposals live on the server; admins, stewards and staff write, members only read; Word and Excel uploads become readable; the browser store goes.

**Files**
- New: `db/migrations/0048_proposal_work.sql`.
- New backend: `backend/app/proposals/{__init__,rubric,readiness,gates,work}.py`, and `api/routes/proposals.py`, `repositories/proposals.py`, `schemas/proposals.py`.
- Edited backend: `api/router.py`, `api/routes/documents.py`, `repositories/documents.py` (docstring), `ingest/vault.py`, `pyproject.toml`.
- Frontend: `frontend/features/ask/views/proposals/*` (`store.ts` becomes `api.ts`, `start.ts` is deleted), plus `ProposalsView.tsx`, `AskWorkspace.tsx`, `FunderMatchView.tsx` and `MatchCard.tsx`.

**Changes**
- **0048:**
  - `proposals` gains `work` and `summary` jsonb (`NOT NULL DEFAULT '{}'`).
  - `proposals_insert` and `proposals_update` become `org_id IN (SELECT app.my_match_org_ids()) OR (SELECT app.is_staff())`: admins and stewards, the same people who may save a Funder Match run. Members lose write; `proposals_read` (`my_org_ids()`) is unchanged, so they still read.
  - `documents_insert` becomes `org_id IN (SELECT app.my_org_ids()) OR (SELECT app.is_staff())`, so a steward can upload in step 2. A member's Doc Vault uploads elsewhere are unchanged.
  - Keep the 0027 `DO` guard.
- **`rubric.py`:** the rubric moves server-side (`proposal-v2`).
  - `DEPENDS_ON`: A2/A3 before A4, A4 before A5/A6, A5 before A15, everything before A1.
  - `sections_for(earlier_phase, template)` adds F4 for an earlier phase and the funder form's own questions as T sections; the form's limits are later.
- **`readiness.py`:** `summary(work)` in the 9 Oct shape, plus `stage`, `facts_open` and `questions_open`.
- **`gates.py`:** ports `start.ts`, using `latest_run` and `get_detail`.
- **`work.py`:**
  - `ALLOWED_PATHS` covers gates, template, style, stage, `sections.<code>.text|done` and `facts.<id>.status|value`.
  - `apply()` runs `SELECT … FOR UPDATE`, then `jsonb_set` per path, then the section-`rev` 409, then recomputes `summary`.
  - Every write appends `{at, by, via, run_id, path, from, to, facts, reason}` to `work.log[]`, where `via` is `rest` or `agent`. The log is kept in full; the context layer reads only the latest entries by other people.
  - It is the only write path: the agent tools, `PATCH /{id}` (title) and `POST /{id}/versions` all call it. ARCHITECTURE.md states the rule.
- **REST routes:** `GET /api/proposals?org&funder`, `POST /api/proposals`, `GET /{id}`, `PATCH /{id}`, `PATCH /{id}/work`, `POST /{id}/advance`. Reads are `require_user`; writes need an admin, steward or staff (403 otherwise, as RLS would refuse anyway), on the caller pool. `GET /{id}` returns `can_edit`, which the screen uses.
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
  - a 409 on a section shows one line, not an error: "Ravi changed this a minute ago. Showing his version." (name and time from `work.log`);
  - proposals saved in the browser are not migrated, and a one-line notice shows if any exist.

**Validation**
- `make migrate`.
- `psql` as member, steward, staff and stranger.
- `curl` the create, PATCH and 409 cases.
- A SeSTA workplan in .docx gets `content_md`.
- `npm run build`.
- **Tests:** `work.apply` (allowed paths only, stale `rev` → 409, every write logged); the 0048 insert and update policies for member, steward, staff and stranger (`integration`).

**Exit gate:** SeSTA's admin starts "SeSTA: women's farm enterprises, Baksa → ABF" from the Match card and answers the gates; the steward opens it on another device and carries on.

### M2: agent skeleton, route, step 1, chat side panel

**Goal:** a `/proposal` agent that knows which proposal it is in, gives each editor their own chat, and advances only through code.

**Files**
- New: `backend/app/proposals/{agent.py,instructions.md,middleware.py,steps.py,context.py}` (`context.py` loads the proposal for the thread and builds the note), `tools/{__init__,proposal_tools,record_tools}.py`.
- Edited: `core/lifespan.py`, `core/security.py`, `frontend/app/api/copilotkit/[[...slug]]/route.ts`.
- New frontend: `proposals/{Stepper,HowItWorks,TellSangam}.tsx` (the proposal screen calls `useAgentContext` with the open step, tab, part and selection) and `toolLabels.ts`.

**Changes**
- **Lifespan:**
  - `AGENT_NAMES["/proposal"]="sangam_proposal"`;
  - `_build_agents` adds `proposal_graph` with `SessionScopedAGUIAgent(..., emit_raw_events=False)`;
  - `AGENT_ACCESS` (#210) declares each route's checks and a path missing from it fails at boot, so `/proposal` gets its own entry: `"/proposal": (proposal_chat_access,)` (decision 1).
  - `proposal_chat_access` reads the proposal id from `proposal-<id>-<user>`, refuses a thread id naming someone else (404), then claims the caller's own thread through `threads.claim_thread` as #213 does, with the proposal's org.
- **Binding to the proposal:** `context.current()` loads the proposal by thread id on the owner pool and refuses unless the caller is staff or in the proposal's org. Tools never take a proposal id from the model.
- **Members read only.** A member has no chat: `proposal_chat_access` refuses their run (403), because every agent tool writes on the owner pool. Every write tool also calls one shared `require_edit(ctx)`, which re-checks `can_edit` from `context.current()` and returns `REFUSED: you can read this proposal` otherwise.
- **Screen:** a member sees every step, the facts and the sections, with no buttons or chat box, and one line: "You can read this proposal. Ask SeSTA's admin to make changes." The Match card shows them "View proposal", never "Start".
- **Supervisor tools:**
  - `read_proposal(part=None)`: one tab or section with the facts it cites; the whole proposal only when no part is given. Working on the budget reads about 8 KB, not 200 KB;
  - `read_match()`, cited `[score:N]`;
  - `read_org_record()`, cited `[org:N]` and `[activity:N]`;
  - `advance_step()`;
- **Middleware:**
  - `ProposalSources` replaces `ChosenSources`. It reads `work.sources`, not the messages, and pins `vault_org` to the proposal's org.
  - `ProposalContext` (as built): reads the proposal fresh on each model call and appends `context.stable(...)` with a cache breakpoint, then `context.live(...)`, to the system message. Never saved to the thread.
  - `StageGate` waits for M3a: M2's only write tool, `advance_step`, checks `steps.exit_check` itself.
  - `CallerNote`, `cheap_summarizer`, `clear_old_tool_results` and `fallback`, as in Import.
- **Browser closed mid-turn:** the plan does not rely on the run carrying on after the stream drops (to be checked in this milestone). Whatever was saved stays; on reopening, the live block says what is done and the chat offers "Continue".
- **Interrupts:** none yet; `ask_user` arrives in M3a.
- **Frontend:**
  - `route.ts` registers `sangam_proposal`;
  - `ProposalShell` becomes the three-step stepper with the canvas's two columns: the step on the left, a side panel on the right (below it on a phone). The panel holds "Your promises from Sangam" before step 1, the chat on step 1 ("Only you see this chat"), and step 2's explainer;
  - under a disabled "Next", the stepper shows `exit_check`'s list in words: "To continue: answer CSR-1.";
  - the panel uses `useAgentChat` on `proposal-<id>-<user>`, with history from `GET /api/proposals/{id}/messages`: the caller's own thread only (reusing `saved_messages(graph_name="proposal_graph")`).
- **Step 2's screen is M3b**, where the readers use it.

**Validation**
- SeSTA's admin and steward each get their own chat on the same proposal and cannot read each other's; a stranger gets 404.
- "Write A3" at step 1 is refused.
- In Langfuse, the second model call of a turn reads the system prompt and tools from the cache (`cache_read_input_tokens` > 0) after a save changed the live block.
- No checkpointed message contains the live block.
- With the problem part open, "make this stronger" works on that part without being told which. After a teammate edits the budget, the next reply mentions it unprompted.
- One answer's SSE payload is about 100 KB, not about 1.7 MB.
- **Tests:** `steps.exit_check` gives the same list for the same `work`; `context.stable/live` are deterministic and the stable block carries no private fact; a member's run gets 403 and a stranger 404; every write tool refuses when `can_edit` is false; two editors get two threads and neither can open the other's.

**Exit gate:** step 1 → 2 happens only after every gate is answered. The gate answers and the open step survive a forced summary.

### M3a: facts and asking

**Goal:** facts from SeSTA's record and the person's answers fill the list, and questions are asked by rule. No reader yet, so this is testable end to end on its own.

**What M2 changes here** (15 Oct): each editor has their own chat, so a question is asked in one person's chat but its answer belongs to the shared proposal.
- **The open question lives in `work.questions`, with who it was asked of**, not only in that chat's interrupt. One open question per person, and a gap asked of one person is not asked of another while it is open. *Example:* Sangam asks the admin about the food gap's causes; the steward's Sangam sees "asked of Admin, waiting" in its live block and asks something else.
- **"Later" frees it for anyone.** A parked question can be asked of whoever next opens that part. An answer becomes a fact both chats see, so nobody is asked twice.
- **The question card sits at the top of the side panel**, above the asker's chat (the canvas's "Sangam's question" card). Members see no question card and no chat; they see facts read-only.
- **Every fact and question change goes through `work.apply` with `via="agent"`**, so it is logged and a teammate's live block says, for example, "Admin confirmed: 1,240 households surveyed". `context._what` names facts by subject, never by code.
- **`StageGate` and `AskGate` are added to `ProposalContext`'s agent here**, the first milestone with tools that write more than the step.

**Files**
- New: `backend/app/proposals/{facts,reliability,questions,records}.py`, `tools/ledger_tools.py`.
- Edited: `proposals/work.py` (allowed paths for new facts and `questions.*`), `proposals/context.py` (the "waiting" lines), `proposals/agent.py`.
- New frontend: `QuestionCard.tsx` in the side panel; `FactList.tsx` in the main column on step 3, per part (each fact: Yes, it's right · No, change it · Don't use it).

**Changes**
- **`add_facts`** verifies each fact by its origin:
  - registry: the marker's row is re-read with fixed SQL and the value must appear in it;
  - vault: `vault.check_findings` against the picked documents;
  - web: an http URL and evidence of at least 20 characters;
  - you_said: the quote must appear in one of the asker's own human messages in their thread; the fact records who said it;
  - derived: it cites `from=[k…]` and stays amber.
  - Tier and colour are set by `reliability.py`.
  - **Idempotent:** a fact with the same origin, source (marker or `document_id` + page), subject and value returns the existing id, so a retried turn adds no duplicates.
- **Where web facts come from.** No proposal reader searches the web. `origin=web` facts arrive through `read_brief`: Import's briefs hold findings researched from public pages, with http links. *Example:* "sesta.org: 120 villages" comes from SeSTA's brief and shows amber.
- **`ask_user`** is an interrupt whose `reason` is one of the three below.
  - `AskGate` (the `ChosenSources` pattern) refuses unless `questions.warranted(...)` holds, this person has no other question open, nobody else holds that gap's question open, and the section is the current one.
  - The resume value is `{kind: "pick", choice}` from a card button, or `{kind: "text", text}` from the asker's chat box (CopilotKit `useInterrupt` in `TellSangam`). `questions.classify(text)` (one `UTILITY_MODEL` call) returns answer, question back or skip, and `ask_user` returns accordingly (decision 4).
  - Only an answer becomes a you_said fact. A question back leaves `work.questions.open` unchanged; a skip sets it to `parked`, and `AskGate` lets a parked question be asked again only for the part on screen or at "Before you send it".
  - Before a parked question is asked again, `questions.warranted(...)` runs again; if a fact now fills the gap, the question closes without being asked. If the fact that answered a question is later corrected or rejected, the gap returns and the question can be asked again.
  - *Example:* "Do you have a baseline survey?" is parked; the person then ticks the March 2026 survey, its reader adds the figure, and the question is never shown again.

| Reason to ask | Code check | SeSTA → ABF example |
|---|---|---|
| Missing | A required Strong element has no fact | A6 needs a baseline; there is "412 SHGs" but no survey figure |
| Sources disagree | Same kind, subject and period at equal tier, different values | the 2024-25 report says 96 villages; the 2023-24 report, 104 |
| Org's call | The kind is programme, amount or gate, or the draft needs a number no fact gives (no suggestion offered) | Baksa farm enterprises or Udalguri SHG federations? · ABF's ceiling is ₹5 crore, but SeSTA has no requested amount |

- **Question shape:** found → missing → why the funder cares → suggestion.
  - *Example:* "Found 412 SHGs [k12] in your 2024-25 report p.14. Missing: an outcome for the last 12 months. ABF scores A6 on outcomes, not counts. Suggestion: the March 2026 household survey, if you have it."
- **Tests:** `reliability`, `questions.warranted` (each of the three reasons and the unwarranted case), `add_facts` verification and idempotency, `AskGate` refusing a gap already open with a teammate.

**Validation:** with only SeSTA's record, the agent adds registry facts, asks one warranted question, and an `ask_user` with no warrant is refused. A typed question back is answered and the card stays. The admin parks a question; the steward opening that part is asked it; the admin's answer to another shows as a fact in the steward's screen.

**Exit gate:** registry and you_said facts show in words with their buttons; one question at a time, by rule, and never the same one to two people.

### M3b: the readers and step 2

**Goal:** what ABF wants and what SeSTA's ticked files say become facts, read in parallel, and a failed or repeated read loses nothing.

**Files**
- New: `tools/reading_tools.py`, `prompts/{funder_file_reader,evidence_reader}.md`.
- New frontend: step 2's "Write the first draft" button and the readers' progress (M2 already has the form, documents and style), step 2's side-panel explainer ("What happens when you press Write the first draft"), and "What ABF looks for" on F1.

**Changes**
- **`read_brief(entity)`** resolves `entity_research.resolved_funder_id` / `resolved_org_id` before the catalog slug, and returns `brief.record()` facts.
- **`read_template()`** (decision 6).
- **`funder-file-reader`** (`RESEARCH_MODEL`, isolated):
  - tools: `read_brief`, `read_document_pages` (only documents linked to this funder), `read_template`, `add_facts`;
  - middleware: `filesystem(backend)`, `ProposalSources`, `fallback`;
  - no web tool and no Doc Vault tool;
  - returns `FunderWants`: priorities, places, eligibility, terminology, past grants, the form's questions. It says plainly what it did not find (a funder with no brief yields little; only staff and stewards can run Scout since #207), and the form link or upload in step 2 fills the gap.
- **`evidence-reader`** (`RESEARCH_MODEL`, isolated):
  - tools: `list_vault_documents`, `read_vault_document`, `read_brief`, `add_facts`;
  - middleware: `filesystem(backend, evict=False)`, `RunSources()`, `DropFilesOnExit()`, `fallback`;
  - one per ticked file, up to `MAX_PARALLEL_RESEARCH` at once;
  - no web tools, and nothing written to `vault_research`.
- **Reader status in `work.readers`:** `{document_id: running | done | failed, error, at}`. A file whose reader fails shows one line, "Couldn't read Workplan 2025.docx. Try again", which re-runs that file only; drafting goes on with gaps where it would have helped. A re-read replaces that file's `proposed` facts and never a confirmed one.
- **Exit checks in `steps.py`:** step 1's is built (M2). Step 2: form set or skipped, style set, "Write the first draft" pressed.
- **Who runs the readers:** the editor who presses "Write the first draft", in their own chat turn. Progress is in `work.readers`, so every teammate's screen shows it. While readers run, a second press is refused with "Admin started reading the files 2 min ago": the one lock in the feature, on reading only, never on chatting.
- **Tests:** `ProposalSources` refuses an unticked file; each reader's compiled graph carries only its declared tools and no web tool; re-reading a file keeps confirmed facts.

**Validation:** SeSTA → ABF on local with a seeded ABF brief and two Doc Vault PDFs. The funder-file reader's trace has no web call and no SeSTA Doc Vault text. One reader forced to fail leaves the other's facts and offers "Try again".

**Exit gate:** ABF's priorities are facts, the readers ran in parallel, and one failed file can be retried alone.

### M4: writing section by section

**Goal:** sections drafted in dependency order, each traced to cited facts and scored 0–2.

The first draft is written tab by tab, one turn per tab, with a marked gap where nothing supports the text; then
`ask_user` closes the gaps one at a time.

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

- **A stopped turn:** each section saves on its own, so a timeout or failed run loses only the section in progress. The chat then shows one line, "Sangam stopped after The Idea. Continue?", and the next turn picks up from `work`.

- **Tests:** `trace` matches numbers, lakh and crore, places and names, and ignores FY and Schedule VII patterns.

**Validation:** SeSTA's A3 is refused once for an untraced "62%", then saved. A1 is written last.

**Exit gate:** a full draft where every number cites a fact.

### M5: review

**Goal:** the person checks every fact, a correction reaches every section that uses it, and readiness is computed.

**Files**
- New: `backend/app/proposals/review.py`; routes `POST /{id}/facts/confirm` and `POST /{id}/facts/{k}/correct`.
- New frontend: `ReviewCard.tsx`.

**Changes**
- **Facts:** each with *Yes, it's right* · *No, change it* · *Don't use it*, plus "Confirm all". Only confirmed facts reach the final text.
- **Correct:**
  - it creates a you_said fact with `supersedes=k` and sets the old one to `corrected`;
  - where the old value appears verbatim in a sentence that cites k, code replaces it;
  - otherwise the section is marked `needs_rewrite` and goes back through `write_section`.
  - derived facts whose `from=[k…]` includes k go back to `proposed` (amber), so the person checks them again.
  - *Example:* villages corrected from 120 to 96 fixes A2 and A1 in place, and A4's "reach all 120" is flagged for a rewrite. Households 1,240 → 1,180 turns "38% = 471 households" amber.
- **Ready:**
  - both gates;
  - no core section at 0;
  - A6, A15 and F1 at 2;
  - no used fact still `proposed`;
  - no open "sources disagree" question.
- **"Before you send it" has two lists.** *Fix first* (these stop "Ready"): a gate answered No, a used fact not confirmed, sources that disagree, a core section at 0. *Worth checking* (shown, never blocking): a score of 1, a gate promised "before sending", a parked question, an `[Add: …]` gap. Download always works and the Word file highlights what is left.

- **Tests:** `review.correct` replaces in place, flags for rewrite, and turns derived facts amber; readiness puts each case in *Fix first* or *Worth checking*.

**Exit gate:** "Before you send it" lists what is left, including any gate answered "We'll have it before sending".

### M6: finish

**Goal:** assemble, a checked polish, a .docx in the Doc Vault, and versions.

**Files**
- New: `backend/app/proposals/{polish,assemble}.py`, `prompts/polish.md`; routes `POST /{id}/polish` and `POST /{id}/versions`.
- New frontend: `FinishCard.tsx`. The main action is "Download as a Word file"; "Save a copy" writes the version. Sangam sends nothing to the funder.

**Changes**
- **Polish:** one `Settings.model` call. `trace.extract` runs before and after.
  - Any number, place or name added, dropped or changed refuses the polish and shows the difference.
  - The result is stored with a hash of the sections, which drives the stale banner.
- **.docx:** built from `work.polished` (title, funder and date, headings, highlighted `[Add:]` gaps).
  - Stored at `<org_id>/proposals/<id>/v<N>.docx`.
  - A `documents` row with `doc_type 'proposal_draft'` and `is_ai_generated`, inserted on the caller pool.
  - `work.versions[]` gets `{n, document_id, at, by, facts_snapshot}`.

- **Tests:** the code part of the polish check refuses any number, place or name that changed.

**Validation:** a polish that turns "₹4.2 crore" into "₹42 lakh" is refused. v2 keeps v1. A steward can save a version.

**Exit gate:** SeSTA downloads v1.docx from the Doc Vault, with its facts snapshot.

**Every PR, M1–M6**
- Run `make wiki-update` and add a CHANGELOG line.
- Edit `docs/ARCHITECTURE.md` where a rule changes:
  - M1: "a steward never writes", "proposals live in localStorage", and that a member reads a proposal but does not edit it;
  - M2: "two agents".
- Root `CLAUDE.md` gets 0048 and the third agent.
- Frontend PRs sync the design system (`docs/DESIGN_SYSTEM.md`).

**Browser test before the next milestone.** Every milestone here has UI, so each ends with a browser run on the local
stack (`make up`, `make seed`, `make match ORG=sesta`), driven through Claude in Chrome, before the next one starts:
- walk that milestone's exit gate end to end as SeSTA's admin, then as a steward, a member (read only) and a stranger (404);
- repeat the main path at phone width (390 px);
- check the browser console and network for errors, and that no storage code or marker shows on screen;
- record a GIF of the main path and attach it to the PR with what was checked;
- anything broken is fixed in the same PR, and the next milestone does not start until the run passes.

| Milestone | What the browser run walks |
|---|---|
| M1 | Start from the Match card as admin → answer the gates → reopen on a second browser profile as steward; a member sees "View proposal" and no buttons |
| M2 | Stepper and "How this works"; step 1 → 2 only once every gate is answered; admin and steward each see only their own chat, in the side panel; a member sees no chat |
| M3a | Facts from SeSTA's record show sources in words with Yes / No / Don't use it; one question card; a typed question back is answered and the card stays; "later" parks it |
| M3b | Step 2: link, upload or skip the form; tick files; "Write the first draft" → the readers' progress; one file forced to fail shows "Try again" and the rest carry on |
| M4 | Each tab's parts draft with marked gaps; a part's score moves from 1 to 2 after an answer; hints tick off |
| M5 | Correct a fact and watch every part that used it update or get flagged; "Before you send it" lists the open CSR-1 gate |
| M6 | Smooth the language; the check passes or names the change; download the Word file and open it; version 1 is listed |

## 6. Test plan

**New tests, for the code-only safeguards only.** An exception to the usual "no new tests in a PR", because these checks are what keep the agent safe and a browser run cannot prove them. Each milestone's **Tests** line lists its own; all but the RLS test run with no database.

| Safeguard | Milestone |
|---|---|
| `work.apply`: allowed paths, stale `rev` → 409, log | M1 |
| 0048 RLS: member, steward, staff, stranger (`integration`) | M1 |
| `steps.exit_check`, `context.stable/live`, access (403/404, `can_edit`), own thread per person | M2 |
| `reliability`, `questions.warranted`, `add_facts` verification and idempotency | M3a |
| `ProposalSources`; readers carry only their declared tools and no web tool; a re-read keeps confirmed facts | M3b |
| `trace` | M4 |
| `review.correct`, readiness lists | M5 |
| polish check (code part) | M6 |

No tests for model output, and no evals. These existing tests must stay green:

| Test | Why it matters here |
|---|---|
| `tests/test_ingest.py::test_every_tool_defined_is_also_registered` | Green only if the Import tools are imported, not redefined |
| `tests/test_ingest.py` prompt/instructions tests | Import only; confirm unchanged |
| `tests/test_harness.py` | Builds Ask and Import only; the proposal readers' own tool test is in M3b |
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
- **No evals.** One SeSTA → ABF run on local, with its cost recorded in Langfuse (`sangam_proposal`).

**Latency and cost budgets.** Set before building; checked on the first SeSTA → ABF run and the first three real proposals. A budget broken there gets a cap (for example a page limit per reader), not a new number.

| What | Budget |
|---|---|
| REST read / save (bom1) | p95 under 300 ms / under 500 ms |
| Agents built on first use | under 1 s |
| First word of a chat reply | under 5 s |
| Answer → next question card | under 30 s |
| Readers, 5 files in parallel | under 5 min |
| Drafting one tab / the whole first draft | under 4 min / under 20 min |
| Polish / Word file | under 60 s / under 10 s |
| Cached share of the supervisor's input tokens | at least 70% |
| Cost to the first draft | target set from the first run; estimate under $5 |

## 7. Risks and edge cases

| Risk | Example and mitigation |
|---|---|
| First-turn latency | Three graphs compile on the first chat turn. Measure "Agents built on first use"; split loading per graph if it passes ~1 s |
| A member writing through the agent | Agent tools run on the owner pool, past RLS. `proposal_chat_access` refuses a member's run, and each write tool re-checks `can_edit` |
| Owner-pool tools skip RLS | A steward of two NGOs must not reach `proposal-43` by guessing. `context.current()` is the guard |
| A reader seeing more than it should | SeSTA's unticked salary sheet is never opened: `ProposalSources` refuses it. The funder-file reader has no Doc Vault tool |
| `work` size | ~200 facts plus 19 sections is about 150–200 KB, rewritten on each write, and the full log adds about 300 bytes per change. The list reads only `summary`; the agent reads one part at a time |
| Trace false positives | "FY2024-25" and "Schedule VII" read as numbers. Exempt fiscal-year patterns and taxonomy codes |
| Polish refusal loop | Rewording lakh as crore is refused on purpose, and the polish prompt says so |
| Cost | One reader per ticked file, the funder-file reader, and one Opus turn per tab. Measure on the first three proposals |
| Saved .docx in Scout's Doc Vault list | "v1.docx" shows up for Scout's vault-reader. Documented, not fixed |
| Screen context is client input | A tampered context names another proposal's part. It sets focus only: `context.current()` binds the proposal by thread, and unknown part codes are dropped |
| Long turns | Several sections in one turn approach 1800 s. One section per turn unless the person asks |
| A reader fails or a turn is retried | 4 of 5 readers finish: their facts are saved, the fifth shows "Try again" for that file alone. A retried turn adds no duplicate facts (`add_facts` is idempotent) and a stale section save gets 409 |
| A funder with no research brief | Only staff and stewards can run Scout (#207), so an admin cannot refresh ABF's brief. The funder-file reader says what it did not find, and step 2 asks for the form link or upload |
| Two people chat at once | Both run. If both save the same section, the second gets 409 (stale `rev`) and Sangam says a teammate changed it |

## 8. Acceptance criteria

1. SeSTA's admin starts a SeSTA → ABF proposal, and a steward or staff member starts a second. Both appear in the list on any device.
2. A stranger gets 404 on the proposal, its messages and its thread. A member can read the proposal and its chat, and gets 403 on any edit, start or new chat message.
3. Step 2 opens once every gate is answered and step 3 once the first draft is asked for. Reopening an earlier step keeps later work.
4. Only ticked files are read. A read outside them is refused, even days later after the chat was summarised.
5. Every fact shown has a colour, a source and a status.
6. At most one question is open. It names its reason and follows found → missing → why → suggestion, with no suggestion for an inferred number.
   - A question typed while one is open is answered, and the open question stays open. "Later" parks it; it returns with its part.
7. A question with no warranting gap is refused.
8. A section with an untraced number, place or name is refused. Saved sections cite ⟦k⟧ and carry a score from 0 to 2.
9. Correcting a fact updates or flags every section that used it. Ready requires every used fact to be confirmed or corrected.
10. A polish that changes any number, place or name is refused.
11. Each version is a .docx in the Doc Vault with a facts snapshot, and earlier versions stay.
12. Doc Vault facts never appear in a brief, in `entity_research` or `vault_research`, or in the funder-file reader's context. No reader makes a web call; web facts come only from Import's briefs.
13. Ask and Scout are unchanged: an Ask question and a Scout import still run in the browser, and Recent Chats is unchanged.
14. No storage code or marker appears on screen; every source is in words.
15. A gate answered "We'll have it before sending" shows as open on "Before you send it" until it is done.
16. Every agent turn knows the step, the part on screen and what changed since its last reply, without calling a tool. A teammate's edit is mentioned on the next turn.

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
| `backend/tests/test_proposals_*.py` | new | The code-only safeguards, per milestone (decision 18) |
| `docs/ARCHITECTURE.md`, `CLAUDE.md`, `docs/CHANGELOG.md`, `openwiki/**` | edit | Rules, facts, changelog, wiki |

## 10. Order of work

- [ ] M1: 0048, the REST resource, uploads, the list on the API. Exit: shared across devices.
- [ ] M2: `/proposal`, own-chat access, agent skeleton, sources kept in `work`, side panel. Exit: admin and steward each have their own chat on one proposal.
- [ ] M3a: facts, reliability, `ask_user` with AskGate and reply sorting, questions shared across each person's chat. Exit: facts in words; one question at a time, by rule, never asked of two people.
- [ ] M3b: the readers, reader status and retry, step 2. Exit: readers ran in parallel; one failed file retried alone.
- [ ] M4: `write_section`, trace, grade, order. Exit: a fully traced draft.
- [ ] M5: review, propagation, ready. Exit: Ready or the exact list.
- [ ] M6: checked polish, .docx, versions. Exit: v1.docx in the Doc Vault.
- [ ] Each PR: a passing browser run (above) before the next milestone starts, `make wiki-update`, a CHANGELOG line, ARCHITECTURE and CLAUDE.md where rules change, a design-system sync, that milestone's safeguard tests, `npm run build`, `ruff check .`, `pytest`, and `pytest -m integration`.

## 11. Later (not in M1–M6)

Cut from the first version on 15 Oct (decision 22); each can be added without reshaping M1–M6:
- **Freshness and corroboration in fact colours:** windows by kind (registrations until expiry, financials the last FY, outcomes 24 months, staff 6 months), and a second source raising a fact one colour.
- **Three more reasons to ask:** stale ("income up 38%" from FY2021-22), weak support (A15 resting only on a web figure).
- **Derived figures recomputed** after a correction (1,240 → 1,180 turning 471 into 448) instead of turning amber.
- **A changed file noticed:** a `content_hash` on file facts, checked on open, sending its facts back to "please check".
- **A promise check in polish:** "We will train 400 women" → "We aim to…" refused.
- **`flag_conflict`** for clashes in meaning, such as a "3-year project" against a 24-month workplan.
- **The funder form's limits** (summary up to 2,000 characters) checked on each section.
- **Staff numbers:** a saved query over `work.log`: days per step, refusals by reason, corrections by origin, idle proposals.

- **"How others have done this"** (14 Oct): once The Idea is drafted, a goal card from A2–A4 drives a `landscape-reader`, the only reader with web search, that finds similar work in the region, India and the world, with links and the funder's closest past grants. Results are amber web facts the person marks "Useful" and confirms. It needs: Import's web tools imported, searches written from the goal card only, `add_facts` re-fetching the page to find the quote, and decision 11, criterion 12 and the M3b tool test edited to allow that one reader. One milestone after M3b; nothing in M1–M6 changes.
