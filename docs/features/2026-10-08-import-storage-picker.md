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
     *(Superseded by both addenda below: any bucket, any folder.)*
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

## Addendum, 2026-10-08: staff choose the bucket; a reader finds the names inside a sheet

Testing showed two gaps:
- **No bucket choice.** The agent listed buckets silently, and the prompt hard-coded
  `staff-sources`.
- **No way to read the names in a sheet.** A request such as "research every funder in the CSO
  workbook" stalled, because a researcher needs a name before `read_source_rows` can search.

Decided: the supervisor never reads rows (hand off only), and any bucket may be picked
(`.xlsx` only).

### M1: bucket pause, any bucket
Exit gate: the person picks the bucket, then the files; an `.xlsx` from a non-staff bucket is
read.
- **The pause.** `list_bucket_files` joins `INTERRUPT_ON`, so `HumanInTheLoopMiddleware` pauses
  there. The person's bucket comes back as an `edit` of the `bucket` argument.
- **Any bucket.** `check_pick`, `register` and `_workbook` accept any bucket, and `picked_id`
  hashes the qualified path. (`staff-sources` first kept its registry-key folder rule; the next
  addendum drops it.)
- **Frontend.** `BucketPicker` sits beside `SourcePicker`, and `PausedPick` routes on the action's
  name.

### M2: `workbook-reader` subagent
Exit gate: "research every funder in document 42" returns names with cell markers, then one
researcher per name.
- **The subagent.** It is isolated, its one tool is `read_workbook(documents, sheet, start_row,
  limit)`, and it returns `WorkbookEntities` (name, kind, marker).
- **The reader.** `staff_sources.browse` returns an outline when no sheet is given, otherwise a
  page of rows. It renders through `render`, so markers and redaction still apply.
- **The supervisor.** It launches the reader, then a researcher per name with the same document
  ids.

## Addendum, 2026-10-08: no folder rule

Testing on staging, `staff-sources/CSRAnalytics-Report-FY-2014-2025.xlsx` was refused because it
sits at the bucket root. The registry-key folder requirement was a hardcoded convention the
upload script followed and a dashboard upload need not. The agent then guessed folder names.

- **What changed.** `check_pick` accepts any `.xlsx` at any depth, in any bucket.
- **What a folder still does.** A first folder named for a registry key (e.g. `mca_csr/`) still
  sets the dataset's `source_name`, which selects the unit in `SOURCE_UNITS` (crore for
  `mca_csr`). For any other file, `source_name` is the bucket.
- **The cost.** A file with no registry-key folder gets no default unit. Its amounts promote only
  when the cell states a unit, or when no unit can be checked against.
- **Exit gate.** The root-level CSR workbook is picked, registered and read by `workbook-reader`.
