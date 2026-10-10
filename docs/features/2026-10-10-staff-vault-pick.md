# Import: choose sources on the Start step, right after the task

## Context

Today the person picks a task and names on the Start step, the run starts, and only then does the run pause on the "Where should Sangam read from?" card. On branch `feat/staff-vault-pick` I added an org search box to that card, so staff could reach any organisation's vault. The user doesn't want that. Instead:

1. **Sources come right after the task.** Click "Research a funder" or "Check an NGO" and the Start step immediately lists where Sangam can read from: public websites, Sangam's library, the Doc Vault files of the person's own organisation(s), and for staff the team spreadsheets. The person ticks, enters names, then Go. The mid-run card no longer appears, and neither does the search box.
2. **Private files only for your own org.** Only the vault files of organisations the person belongs to are listed. Staff are no exception.
   - Example: a steward of Arpan sees Arpan's private files. A staff member who belongs to Arpan sees them too. A staff member with no membership sees no Doc Vault section.
3. **Nothing pre-ticked, and everything stays in one thread.** Go is disabled until at least one source and one name are chosen.

The backend contract doesn't change: the supervisor still calls `choose_sources` first, the answer is still stored in the checkpoint, and `RunSources` still refuses any read outside it. The only difference is that the screen answers that pause straight away with the Start-step picks.

## Changes on `feat/staff-vault-pick`

**Undo the org search** (from commit `b955efe`):
- Remove `OrgVault`, plus `searchOrgs` / `orgById` in `frontend/features/ingest/lib/vaultFiles.ts`.
- Revert the `vault_org` proposal rule in `backend/app/ingest/instructions.md` step 3 and in the `choose_sources` docstring (`backend/app/ingest/tools/pipeline_tools.py`).
- Keep the `_org` hardening in `vault_tools.py`, the neutral vault wording, and `vaultFilesOf`.

**A shared picker:** new `frontend/features/ingest/components/SourcePicker.tsx`.
- It is controlled: it takes `value: SourcesChoice` and `onChange`.
- It shows the web and library options, the own-org vault chips (one org per run, keeping the existing `toggleVault` rule), and team spreadsheets for staff.
- It is lifted out of `Card` in `SourcesCard.tsx`, along with `useWorkbooks`, `Option`, `VaultChips` and `VAULT_HINT`.
- A shared `EMPTY_SOURCES` (everything off) lives in `lib/sourcePick.ts`.

**Start step (`frontend/features/ingest/components/StartStep.tsx`):**
- The task starts unselected (`useState<ImportTask | null>(null)`).
- Once "funder" or "ngo" is clicked, show a "Where should Sangam read from?" block with `<SourcePicker>`, nothing ticked, above the names.
- The news task runs the adapter and has no picker.
- `onStart(prompt, sources)`. Go is disabled until a task is chosen, at least one name is entered, and at least one source is ticked.
- The sub-line changes to "Choose what to find out, where Sangam may read from, and who. Every answer shows its source."
- StartStep now needs `vaultFiles`, so ImportWorkspace passes it down (it already has it).

**Workspace (`frontend/features/ingest/ImportWorkspace.tsx`):**
- Keep `const [preset, setPreset] = useState<SourcesChoice | null>(null)` for the thread. Set it in `onStart`, then `submit(prompt)` as today. Clear it on Start over.
- Pass `preset` to `<SourcesCard>`.

**`SourcesCard.tsx`:**
- With a `preset`, the interrupt render mounts a tiny `AutoAnswer` that calls `resolve({decisions: [sourcesDecision(preset)]})` once, in an effect, and renders nothing. A follow-up message in the same thread that pauses again gets the same answer, so the person is never asked twice.
- Without a preset, it shows the card using `<SourcePicker>` seeded with `EMPTY_SOURCES`, not the agent's proposal. That happens when:
  - the request was typed under "Advanced: type your own request", or
  - the page was reloaded mid-run.

## Not doing

- No backend contract change: `choose_sources`, `INTERRUPT_ON`, `ChosenSources`, `RunSources` and the existing tests stay as they are.
- No new endpoint, table, CSS class or design-system component. The picker reuses `.import-file`, `.import-chips`, `.import-chip` and `.import-names`.
  - The Import screen does change, so the UI kit's `Import.jsx` start page still needs the same sync noted before. That needs V's edit access; flag it in the PR.
- No new tests (repo rule); fix any that break.

## Verification

- `cd backend && pytest -m "not integration"` and `ruff check` on the touched files.
- `cd frontend && npm run lint && npm run build`.
- On the local stack (main checkout is on this branch and hot-reloads), signed in at localhost:3000/import:
  1. Click "Research a funder": the sources block appears with nothing ticked, and Go is disabled. Tick "Public websites", add a name, Go. The run starts and **no** sources card appears; the trace shows researchers reading the web only.
  2. As a member of an org with private files, click "Check an NGO": that org's files are listed. Tick one plus the library, Go. The trace shows the vault-reader reading only that file.
  3. Staff with no membership: no Doc Vault section, and team spreadsheets are listed.
  4. Advanced typed request: the mid-run card still appears, with nothing pre-ticked.
