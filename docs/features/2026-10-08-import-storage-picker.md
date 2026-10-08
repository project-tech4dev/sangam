# Import picks its source files from Storage, with a human in the loop

## Context
Today `read_source_rows` sees only workbooks registered by `make staff-source` (object + `documents`
row). A file dropped into a bucket from the Supabase dashboard is invisible. The new flow:

1. Sangam Import lists the Storage buckets, then the files in one.
2. It proposes which files to use.
3. **Staff confirm or edit the pick in the Import screen.** This is LangChain's
   `HumanInTheLoopMiddleware`, via deepagents' `interrupt_on`.
4. Only the chosen files are read.

Supabase MCP is not used: it has no object download, and it brings `execute_sql` with a personal
access token.

**Example:** "Research Tata Trusts using the CSR filings". The supervisor calls
`list_storage_buckets` → `staff-sources, org-vault, source-archive`. Then
`list_bucket_files("staff-sources")` → `mca_csr/csr_2023-24.xlsx`, `mca_csr/csr_2022-23.xlsx`,
`cso/funders.xlsx`. It calls `select_source_files(["staff-sources/mca_csr/csr_2023-24.xlsx"])` and
the run pauses. Staff see a checklist in Import, tick `csr_2022-23.xlsx` too, and press Confirm. The
run resumes with both files. Each gets its `documents` row, and the researchers read only those two.

The `documents` row stays: the `[source:<doc id>#sheet!cell]` marker, promote's `_staff_datasets`
and `hold_unmarked` all key on it. The selection step creates it, so the upload script stops being
required.

## Milestone 0: commit the plan
Worktree off `origin/master`, branch `feat/import-storage-picker`, and this plan as
`docs/features/2026-10-08-import-storage-picker.md`, committed before any code.

## Milestone 1: backend (exit gate: a run pauses at `select_source_files` and resumes)
1. **`backend/app/integrations/storage.py`**:
   - `list_buckets()` returns `GET /bucket` (id, public).
   - `list_all(bucket, prefix="")` pages `/object/list` recursively into folders, returning files
     with `key`, `size` and `updated_at`. The existing `list_prefix` caps at 20 and is one level
     deep.
2. **`backend/app/ingest/tools/pipeline_tools.py`** (beside `read_source_rows`) gets three supervisor tools. They return errors
   and never raise; output is counts and paths, never cell values.
   - `list_storage_buckets()`
   - `list_bucket_files(bucket, prefix="")`: `.xlsx` only, since `read_source_rows` reads
     workbooks.
   - `select_source_files(paths: list[str])`: runs only after approval. For each path it downloads
     the file (existing `storage.download`), takes `storage.content_hash`, and calls the existing
     `documents_repo.upsert_source_dataset`. It returns `path → document id`. Only
     `staff-sources/<registry key>/….xlsx` is selectable; anything else is refused, not copied,
     because `org-vault` holds orgs' private files and copying them would change who can read them.
     The downloaded bytes prime `read_rows`' cache, so a wave of researchers does not re-download.
3. **`backend/app/ingest/agent.py`**: add LangChain's `HumanInTheLoopMiddleware` (from
   `langchain.agents.middleware`) to the supervisor:
   `interrupt_on={"select_source_files": {"allowed_decisions": ["approve", "edit", "reject"],
   "description": "Confirm the files Import will read"}}`. Wire it through `create_deep_agent`'s
   `interrupt_on=`, which builds exactly that middleware (`deepagents/graph.py:921`), so it lands in
   deepagents' ordering rather than as a second copy in `middleware=[…]`. Add the three tools to the
   supervisor's `TOOLS`. Confirm `harness.install()` / `filesystem()` leave the middleware in
   place. The middleware calls LangGraph `interrupt()`, which the existing `AsyncPostgresSaver`
   checkpoints. `ag-ui-langgraph` sends it to the browser and passes the resume back as
   `Command(resume={"decisions": […]})`.
4. **`read_source_rows(name, sheet="", documents: list[int] | None = None)`** in
   `pipeline_tools.py` and `staff_sources.read_rows`: restrict to the given document ids. When none
   are given, keep today's behaviour of reading all registered datasets.
5. **Prompts**:
   - `app/ingest/instructions.md`: describe the three tools. Add the rule "pick files with
     `select_source_files`, then put the returned document ids in each researcher's task".
   - `prompts/entity_researcher.md`: pass `documents=` to `read_source_rows`.
   - `skills/funder-intake-research` and `ngo-credential-research`: replace "uploaded with make
     staff-source" with the picker step.

## Milestone 2: frontend (exit gate: confirm/edit/reject works in the browser)
1. **`frontend/features/ingest/components/SourcePicker.tsx`**: a checklist of the proposed paths
   (pre-ticked) plus every other file the run's `list_bucket_files` printed, with Confirm and
   "Continue without staff data" (reject) buttons. It uses the existing
   `components/ui` primitives and the design-system tokens only.
2. **`ImportWorkspace.tsx`**: mount `PausedPick` (in `SourcePicker.tsx`) once the thread's agent
   is ready. It calls `useInterrupt({ agentId: "sangam-import-<threadId>", renderInChat: false,
   enabled: e => tool is select_source_files, render })` from `@copilotkit/react-core/v2`. It has
   to wait for ready because `useAgent` looks a bare id up synchronously and the proxied agent
   registers in an effect. It resolves with the
   HITL resume shape:
   `{decisions: [<one decision>]}`, where the decision is
   - `{type: "approve"}`
   - `{type: "edit", edited_action: {name: "select_source_files", args: {paths}}}` when the ticks
     changed
   - `{type: "reject", message}`
3. **`frontend/features/ingest/lib/toolLabels.ts`**: add labels for the three new tools.
4. Run `npm run lint && npm run build`.

## Docs
- CLAUDE.md: the Import tool list, and "`make staff-source` is optional; the picker registers
  files".
- `docs/SKILLS.md` if the skills' flow is described there.
- Sync the Design System project if `SourcePicker` introduces a new component look.

No new tests (repo rule). Fix the existing ones this breaks: the package-walk registration test,
the harness tool lists in `tests/test_harness.py`, and the prompt-names-every-tool test.

## Verification
- `cd backend && ruff check . && pytest -m "not integration"`, then `cd frontend && npm run lint &&
  npm run build`.
- `make up`, sign in as staff, open `/ask?view=import`. Upload a test `.xlsx` to `staff-sources`
  via the Supabase dashboard. Ask Import to research a funder named in it.
- Confirm the run pauses with the picker. Then check each decision:
  - **Edit** (untick a file): the run continues with the remaining file, a `documents` row exists,
    and the researcher's trace shows `read_source_rows(…, documents=[id])` with a `[source:id#…]`
    marker.
  - **Reject**: the model is told and continues without staff data.
  - **Known gap**: reloading the page mid-pause orphans that run. `ImportWorkspace` mints a new
    thread per mount, so the next message starts fresh.
