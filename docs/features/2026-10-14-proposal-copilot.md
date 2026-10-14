# Proposal Copilot: a human-in-the-loop agent that builds a proposal with the NGO

Draft v2 · 2026-10-14 · branch `feat/proposal-copilot`

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
`9e7e6f0`. The running example is SeSTA (the NGO) writing to Axis Bank Foundation (ABF, the funder).

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
- `write_section`: trace check, then grade, then `rev`;
- `flag_conflict`: both facts exist and are of equal tier.

**Architecture**

```
 Browser · Proposals → one proposal
 ┌──────────────────────────────────────────────────────────────┐
 │ 3 steps │ step 3: 5 tabs · part (hints · facts · draft) │ chat │
 └────┬───────────────────┬─────────────────────────────┬───────┘
      │ REST              │ question answers            │ chat
      ▼                   ▼                             ▼
 ┌──────────────┐   ┌─────────────────────────────────────────────────┐
 │ /api/        │   │ /proposal · thread proposal-<id> · shared       │
 │ proposals    │   │  SUPERVISOR (MODEL)                             │
 │ route→repo→  │   │   reads:  read_proposal · read_org_record ·     │
 │ schema       │   │           read_match                            │
 └──────┬───────┘   │   pauses: ask_user  ◄─ HITL, one at a time      │
        │           │   writes: add_facts · write_section ·           │
        │           │           flag_conflict · advance_step          │
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
 Postgres: proposals.work {stage, gates, template, sources, style, facts[], sections, conflicts, versions}
           funder_matches · programs · funder_activity · document_links · documents
 Storage:  source-archive/entities/<slug>.md (briefs, read-only) · org-vault/<org>/proposals/<id>/vN.docx
```

**One turn, worked through (step 3, The People tab, A11 "Track record"):**
1. The evidence readers have already run, one per ticked file. `ProposalSources` let each read only its own file.
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

**The context layer: the agent is told where it is on every model call, and never has to remember.**
`app/proposals/context.py` is pure code with two functions, `stable(work)` and `live(work, screen, since)`. It is split in
two because deepagents caches the system prompt (`AnthropicPromptCachingMiddleware`), and text there that changes after
every save would invalidate the cached prefix on each call. Its own `MemoryMiddleware` handles changing memory the same way:
a separate block with its own cache breakpoint.

| Block | What it says | Comes from | Where it goes | Changes |
|---|---|---|---|---|
| **Stable** | the proposal, org, funder and programme; the funder's confirmed priorities; the form's sections and limits; gate answers; the writing style | `work` | appended to the system message by `ProposalBrief`, with its own `cache_control` breakpoint (as `MemoryMiddleware(add_cache_control=True)`) | rarely: step 2 done, a priority confirmed, a gate answered |
| **Live** | where the proposal is (step, tab, parts finished, scores, readers done); what is on screen; what changed since the agent last spoke; what is waiting; what it may do next | `work`, `summary`, the screen and `work.log[]`, read fresh each call | added by `ProposalNote` as the last message of that one model call, never written to the graph state, so the chat history and the checkpoint never hold it | every call |

Each line of the live block has its own source and trust:

| Line | Comes from | Trusted for |
|---|---|---|
| Where the proposal is | `work` and `summary` | everything |
| What the person is looking at | the screen, through `useAgentContext` (as Scout sends its ticks) | focus only, never permission. A part code the server doesn't know is dropped |
| What changed since the agent last spoke | `work.log[]`, appended by `work.apply()` with who, what and when; entries after `work.agent_seen` | everything |
| What is waiting | the open question; facts not yet confirmed; parts flagged to rewrite | everything |
| What it may do next | `steps.py` and `DEPENDS_ON` | everything; the tools check again |

*Example*, SeSTA's steward opens the problem part after a colleague edited the budget yesterday.

Stable block (cached; unchanged since step 2):

```
Proposal 42: SeSTA → Axis Bank Foundation · programme: SHG federations, Udalguri
ABF's confirmed priorities: rural livelihoods through community institutions, North-East India; ₹1–5 crore over 3 years
Form: ABF proposal format 2026 · summary up to 2,000 characters · workplan by quarter · §6 convergence with government
Gates: 12A, 80G, standing: yes · CSR-1: will have it before sending · 2025-26 accounts: yes
Style: plain, specific English for a CSR programme officer; ₹ in lakh and crore; every figure with source and year
```

Live block (this call only):

```
Step 3 · 4 of 19 parts finished · readers done (5 files)
On screen: The Idea › The problem, with figures (score 1 of 2) · selected: "38% of the 1,240 households"
Since you last spoke: Ravi changed the budget total to ₹2.4 crore (yesterday 16:10); fact k5 marked "Don't use it"
Waiting: no open question · 3 facts not confirmed · "What will change" flagged to rewrite (uses the old total)
Next allowed: ask one question about this part, or rewrite "What will change"
```

- The details (fact values, section text) stay behind `read_proposal()`, so both blocks stay short however big `work` grows.
- Building them needs no model call.
- `ProposalNote` sets `work.agent_seen` at the end of each run, so "since you last spoke" moves forward.

**What it is tracking lives in the proposal row, not the conversation.** Sources chosen, the open question and confirmed priorities are kept in `work`, because a proposal chat spans days and `cheap_summarizer` drops old tool messages.

**Review and "Before you send it" are mostly code.** Correction propagation, the equal-tier contradiction check, readiness, the polish check and the .docx are deterministic. Polish is one `Settings.model` call made by a REST route.

**Alternatives considered and rejected**
- **An agent per section:** costs too much and splits the fact list.
- **A `proposal_facts` table:** "no new tables" was already decided.
- **Grading with `RubricMiddleware`:** it grades only at the end of a run.
- **Copying the Import tools:** they are imported, so `run_sources`' name sets and `test_every_tool_defined_is_also_registered` still hold.

## 4. Decisions taken (14 Oct)

1. **One shared chat per proposal.** The thread is created by REST with `use_case='proposal'` and `visibility='team_and_stewards'`.
   - A new `proposal_chat_access` opens it with `can_open` and never claims it.
   - So SeSTA's admin and steward share `proposal-42`, and it stays out of Ask's Recent Chats.
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
17. **A context layer on every model call, in two blocks.** A stable block in the system prompt with its own cache breakpoint (`ProposalBrief`), and a live block as the last message of each call, never saved (`ProposalNote`). Both are built by code from `work`, the screen and `work.log`.

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
  - `sections_for(earlier_phase, template)` adds T sections and overlays.
- **`readiness.py`:** `summary(work)` in the 9 Oct shape, plus `stage`, `facts_open` and `questions_open`.
- **`gates.py`:** ports `start.ts`, using `latest_run` and `get_detail`.
- **`work.py`:**
  - `ALLOWED_PATHS` covers gates, template, style, stage, `sections.<code>.text|done` and `facts.<id>.status|value`.
  - `apply()` runs `SELECT … FOR UPDATE`, then `jsonb_set` per path, then the section-`rev` 409, then recomputes `summary`.
  - Every write appends `{at, by, path, from, to}` to `work.log[]` (kept to the last 200), which the context layer reads.
  - The agent tools use the same function.
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
  - proposals saved in the browser are not migrated, and a one-line notice shows if any exist.

**Validation**
- `make migrate`.
- `psql` as member, steward, staff and stranger.
- `curl` the create, PATCH and 409 cases.
- A SeSTA workplan in .docx gets `content_md`.
- `npm run build`.

**Exit gate:** SeSTA's admin starts "SeSTA: women's farm enterprises, Baksa → ABF" from the Match card and answers the gates; the steward opens it on another device and carries on.

### M2: agent skeleton, route, step 1 and the sources card, chat drawer

**Goal:** a `/proposal` agent that knows which proposal it is in, is shared by the team, and advances only through code.

**Files**
- New: `backend/app/proposals/{agent.py,instructions.md,middleware.py,steps.py,context.py}` (`context.py` loads the proposal for the thread and builds the note), `tools/{__init__,proposal_tools,record_tools}.py`.
- Edited: `core/lifespan.py`, `core/security.py`, `frontend/app/api/copilotkit/[[...slug]]/route.ts`.
- New frontend: `proposals/{Stepper,HowItWorks,TellSangam}.tsx` (the proposal screen calls `useAgentContext` with the open step, tab, part and selection) and `toolLabels.ts`.

**Changes**
- **Lifespan:**
  - `AGENT_NAMES["/proposal"]="sangam_proposal"`;
  - `_build_agents` adds `proposal_graph` with `SessionScopedAGUIAgent(..., emit_raw_events=False)`;
  - `_add_agent_route(app, path, access=chat_access)`, with `/proposal` passing `proposal_chat_access` (decision 1).
- **Binding to the proposal:** `context.current()` loads the proposal by thread id on the owner pool and refuses unless the caller is staff or in the proposal's org. Tools never take a proposal id from the model.
- **Members read only.** `proposal_chat_access` lets a member open the thread's history (GET) but refuses a new run (403), because every agent tool writes on the owner pool. Every write tool also re-checks `can_edit` from `context.current()`.
- **Screen:** a member sees every step, the facts and the sections, with no buttons or chat box, and one line: "You can read this proposal. Ask SeSTA's admin to make changes." The Match card shows them "View proposal", never "Start".
- **Supervisor tools:**
  - `read_proposal()`;
  - `read_match()`, cited `[score:N]`;
  - `read_org_record()`, cited `[org:N]` and `[activity:N]`;
  - `advance_step()`;
- **Middleware:**
  - `ProposalSources` replaces `ChosenSources`. It reads `work.sources`, not the messages, and pins `vault_org` to the proposal's org.
  - `StageGate`.
  - `ProposalBrief`: `context.stable(work)` appended to the system message with a `cache_control` breakpoint (the `MemoryMiddleware(add_cache_control=True)` pattern).
  - `ProposalNote`: `context.live(...)` added as the last message of each model call through `request.override(messages=...)`, not returned as a state update. It sets `work.agent_seen` at the end of each run.
  - `CallerNote`, `cheap_summarizer`, `clear_old_tool_results` and `fallback`, as in Import.
- **Interrupts:** none yet; `ask_user` arrives in M3.
- **Frontend:**
  - `route.ts` registers `sangam_proposal`;
  - `ProposalShell` becomes the three-step stepper, with "How this works" shown once before step 1;
  - the drawer uses `useAgentChat`, with history from `GET /api/proposals/{id}/messages` (reusing `saved_messages(graph_name="proposal_graph")`);
  - step 2's form, documents and style are REST writes to `work`, not an interrupt.

**Validation**
- SeSTA's admin and steward open the same thread, and a stranger gets 404.
- "Write A3" at step 1 is refused.
- In Langfuse, the second model call of a turn reads the system prompt and tools from the cache (`cache_read_input_tokens` > 0) after a save changed the live block.
- No checkpointed message contains the live block.
- With the problem part open, "make this stronger" works on that part without being told which. After a teammate edits the budget, the next reply mentions it unprompted.
- One answer's SSE payload is about 100 KB, not about 1.7 MB.

**Exit gate:** step 1 → 2 happens only after every gate is answered. The sources answer survives a forced summary.

### M3: facts, asking, the readers, step 2

**Goal:** what ABF wants and what SeSTA has become facts in the list, and questions are asked by rule.

**Files**
- New: `backend/app/proposals/{facts,reliability,questions,records}.py`, `tools/{ledger_tools,reading_tools}.py`, `prompts/{funder_file_reader,evidence_reader}.md`.
- New frontend: `QuestionCard.tsx`, `FactList.tsx` (each fact: Yes, it's right · No, change it · Don't use it), and "What ABF looks for" on F1.

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
- **`funder-file-reader`** (`RESEARCH_MODEL`, isolated):
  - tools: `read_brief`, `read_document_pages` (only documents linked to this funder), `read_template`, `add_facts`;
  - middleware: `filesystem(backend)`, `ProposalSources`, `fallback`;
  - no web tool and no Doc Vault tool;
  - returns `FunderWants`: priorities, places, eligibility, terminology, past grants, form sections, limits. What it does not find it says, so the form upload opens in step 2.
- **`evidence-reader`** (`RESEARCH_MODEL`, isolated):
  - tools: `list_vault_documents`, `read_vault_document`, `read_brief`, `add_facts`;
  - middleware: `filesystem(backend, evict=False)`, `RunSources()`, `DropFilesOnExit()`, `fallback`;
  - one per ticked file, up to `MAX_PARALLEL_RESEARCH` at once;
  - no web tools, and nothing written to `vault_research`.
- **`ask_user`** is an interrupt whose `reason` is one of the six below.
  - `AskGate` (the `ChosenSources` pattern) refuses unless `questions.warranted(...)` holds, no other question is open, and the section is the current one.
  - The resume value is `{kind: "pick", choice}` from a card button, or `{kind: "text", text}` from the chat box. `questions.classify(text)` (one `UTILITY_MODEL` call) returns answer, question back or skip, and `ask_user` returns accordingly (decision 4).
  - Only an answer becomes a you_said fact. A question back leaves `work.questions.open` unchanged; a skip sets it to `parked`, and `AskGate` lets a parked question be asked again only for the part on screen or at "Before you send it".

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
  - step 1: every gate answered;
  - step 2: form set or skipped, style set, "Write the first draft" pressed.

**Validation:** SeSTA → ABF on local with a seeded ABF brief and two Doc Vault PDFs. The funder-file reader's trace has no web call and no SeSTA Doc Vault text, and an `ask_user` with no warrant is refused.

**Exit gate:** ABF's priorities are facts, the readers ran in parallel, and every fact shows its source in words.

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
  - *Example:* villages corrected from 120 to 96 fixes A2 and A1 in place, and A4's "reach all 120" is flagged for a rewrite.
- **Contradiction pass:** code first, over equal-tier facts. Then the agent's `flag_conflict` for clashes in meaning, such as a "3-year project" against a 24-month workplan.
- **Ready:**
  - both gates;
  - no core section at 0;
  - A6, A15 and F1 at 2;
  - overlays met;
  - no used fact still `proposed`;
  - no open conflict.

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

**Validation:** a polish that turns "₹4.2 crore" into "₹42 lakh" is refused. v2 keeps v1. A steward can save a version.

**Exit gate:** SeSTA downloads v1.docx from the Doc Vault, with its facts snapshot.

**Every PR, M1–M6**
- Run `make wiki-update` and add a CHANGELOG line.
- Edit `docs/ARCHITECTURE.md` where a rule changes:
  - M1: "a steward never writes", "proposals live in localStorage", and that a member reads a proposal but does not edit it;
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
| A member writing through the agent | Agent tools run on the owner pool, past RLS. `proposal_chat_access` refuses a member's run, and each write tool re-checks `can_edit` |
| Owner-pool tools skip RLS | A steward of two NGOs must not reach `proposal-43` by guessing. `context.current()` is the guard |
| A reader seeing more than it should | SeSTA's unticked salary sheet is never opened: `ProposalSources` refuses it. The funder-file reader has no Doc Vault tool |
| `work` size | ~200 facts plus 19 sections is about 150–200 KB, rewritten on each write. The list reads only `summary` |
| Trace false positives | "FY2024-25" and "Schedule VII" read as numbers. Exempt fiscal-year patterns and taxonomy codes |
| Polish refusal loop | Rewording lakh as crore is refused on purpose, and the polish prompt says so |
| Cost | One reader per ticked file, the funder-file reader, and one Opus turn per tab. Measure on the first three proposals |
| Saved .docx in Scout's Doc Vault list | "v1.docx" shows up for Scout's vault-reader. Documented, not fixed |
| Screen context is client input | A tampered context names another proposal's part. It sets focus only: `context.current()` binds the proposal by thread, and unknown part codes are dropped |
| Long turns | Several sections in one turn approach 1800 s. One section per turn unless the person asks |

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
12. Doc Vault facts never appear in a brief, in `entity_research` or `vault_research`, or in the funder-file reader's context. No reader makes a web call.
13. Ask and Scout are unchanged: canary evals pass and Recent Chats is unchanged.
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
| `docs/ARCHITECTURE.md`, `CLAUDE.md`, `docs/CHANGELOG.md`, `openwiki/**` | edit | Rules, facts, changelog, wiki |

## 10. Order of work

- [ ] M1: 0048, the REST resource, uploads, the list on the API. Exit: shared across devices.
- [ ] M2: `/proposal`, shared chat access, agent skeleton, sources kept in `work`, drawer. Exit: admin and steward share a thread.
- [ ] M3: facts, reliability, `ask_user` with AskGate, the readers, step 2. Exit: readers ran in parallel; facts in words.
- [ ] M4: `write_section`, trace, grade, order. Exit: a fully traced draft.
- [ ] M5: review, propagation, conflicts, ready. Exit: Ready or the exact list.
- [ ] M6: checked polish, .docx, versions. Exit: v1.docx in the Doc Vault.
- [ ] Each PR: `make wiki-update`, a CHANGELOG line, ARCHITECTURE and CLAUDE.md where rules change, a design-system sync, `npm run build`, `ruff check .`, `pytest`, and `pytest -m integration`.
