# Staff read any organisation's Doc Vault in Import

## Context

Staff can't use the Doc Vault in Import unless they are a member of the organisation. The backend already allows it: `can_read_org` passes for staff on every org (`backend/app/core/security.py:225`), and `/api/documents` returns every org's private files to staff (`backend/app/repositories/documents.py`). Two things block it:

- The sources card lists vault files only for orgs the person is a member of (`loadVault` loops over `access.orgs`, `frontend/features/ingest/ImportView.tsx:45`).
- The supervisor is told to propose web and library and nothing else (`backend/app/ingest/instructions.md` step 3, and the `choose_sources` docstring).

**Outcome:** a staff member reaches an organisation's vault in one of two ways:
1. **By name in the prompt.** "Research Pratham's credentials from its Doc Vault" → the supervisor finds `[org:42]` in `funder_dossier` and proposes `vault_org=42`. The card opens with Pratham's private files listed, and the staff member ticks them.
2. **On the card.** A staff member types "prat" in an org search box on the card, picks Pratham, and the card lists its files to tick.

The person still makes every pick. A proposal only chooses which org's files the card shows; files are never pre-ticked.

The approved plan is committed as `docs/features/2026-10-10-staff-vault-pick.md` on the feature branch before any code.

## Milestone 1: the supervisor can propose an org (backend, one PR with M2)

- **`backend/app/ingest/instructions.md` step 3:** keep "propose `web=True, library=True`", and add one rule. When the person names an organisation whose own documents they want read, pass `vault_org=<id>` (taken from `funder_dossier`'s `[org:N]` citation) and no `vault_docs`. The card shows that org's files for the person to tick. Rename the "Your organisation's documents" heading to "The organisation's documents".
- **`choose_sources` docstring (`backend/app/ingest/tools/pipeline_tools.py:341`):** same rule; `vault_org` becomes "proposed by you or set by the card". The behaviour is unchanged: the `can_read_org` and `in_vault` checks stay, and `vault_org` without docs is still dropped from the stored `Sources`.
- **Hardening, `_org` in `backend/app/ingest/tools/vault_tools.py`:** use the run's chosen org (`run_sources.CURRENT.vault_org`) when one is set. An empty `org` defaults to it, and a different org is refused. Two reasons:
  - Today a vault-reader could list another org's file titles, because `run_sources.refusal` only checks that some vault files were picked.
  - A staff caller with no memberships currently has to spell out the org name; with this change they don't.
- **Existing tests to adjust, not add:** `test_import_sources.py::TestReadsOutsideTheChoiceRefuse::test_per_tool` if its `list_vault_documents` case changes shape. Per the repo's rule, no new tests.

## Milestone 2: the card lets staff pick the org (frontend)

- **`frontend/features/ingest/components/SourcesCard.tsx`:**
  - Staff get a "Doc Vault" section even when `vaultFiles` is empty. It has a search input that calls `GET /api/orgs?q=<text>&limit=8` (existing, trigram search, `backend/app/repositories/orgs.py:26`) after a 250 ms pause, and lists matches as buttons.
  - Picking an org fetches `GET /api/documents?org=<id>&limit=100` (existing; staff see every org's private rows) and keeps rows with `is_public === false`, which is the same filter `loadVault` uses. They render as the same chips as today.
  - Seed it from the proposal: if `proposal.vault_org` is set and not one of the preloaded `vaultFiles` orgs, fetch that org's name (`GET /api/orgs/{id}`, existing) and its files on mount.
  - The one-org-per-run rule stays: switching org clears the ticks, as `toggleVault` already does.
  - Members who aren't staff see exactly what they see today.
- **Extract the fetch-and-filter** into `frontend/features/ingest/lib/vaultFiles.ts`, used by both `ImportView.loadVault` and the card, so the "private file" rule lives in one place.
- **Wording for a reader who isn't the owner:**
  - Card heading "Your organisation's documents" → "Doc Vault: <org name>".
  - `sourcePick.ts` `readingFrom` "Your Doc Vault" → "Doc Vault".
  - `toolLabels.ts` vault labels "your organisation's" → "the organisation's".
- **Styles go in classes in `globals.css`** (reuse the `.import-*` chip and label classes). The search list is a new small component look, so it gets added to the design system and the `ui_kits/sangam-web/` Import page in the same PR (CLAUDE.md rule).

## Not doing

- No new endpoint, table or column: `/api/orgs?q=`, `/api/orgs/{id}` and `/api/documents?org=` cover it.
- No pre-ticking of files from the prompt.
- No change for non-staff members, beyond the neutral wording.

## Verification

- `cd backend && pytest -m "not integration" && ruff check .`
- `cd frontend && npm run lint && npm run build`
- `make up`, sign in as a staff user with no memberships, open `/import`:
  1. Prompt "Research Pratham's 80G and audited accounts from its Doc Vault". The card opens with Pratham's private files listed and none ticked. Tick two and start. The trace shows `vault-reader` → `read_vault_document` on those ids only, with findings cited `[vault:<id>#p…]`.
  2. A new run without naming an org: search "prat" on the card, pick, tick, start. Same result.
  3. As a member who isn't staff: the card is unchanged and has no org search.
- `pytest tests/test_import_sources.py tests/test_import_vault.py` green.
