# Import for every role: vault first, then the web

Status: PR A (leaks and caller scope) is in progress. PRs B to D follow, stacked.

## Context
Import is staff-only today, and it cannot read an org's Doc Vault. The aim is to open it to three roles:
- **Org member / admin** (one org): researches **any funder**. Their own org's vault files are read first, then the open web. They save their research to the catalog directly, after the same Review pause staff get.
- **Steward** (supports many orgs; can read each one's private and public data): researches **the NGOs it supports and any funder**, vault first, then web. It saves both. This makes the steward role writable for research saves (the database role is read-only today).
- **Staff**: everything they have now, plus **deleting** saved research and undoing a save.

### What the code has today
- **Auth is real.** `core/security.py` verifies the Supabase JWT and gives a `CurrentUser` (`id`, `is_staff`). Roles live in `org_members(role ∈ admin|member|steward)`. The SQL helpers `app.my_org_ids()` and `app.my_writable_org_ids()` exist (`0024`). CLAUDE.md and the README still call auth a stub; they are out of date.
- **Agent tools ignore the caller.** They use the owner pool (`get_pool()`), which bypasses RLS. The only identity a tool can see is the `chat_user_id` ContextVar (`security.py:206`). Import sits behind `require_staff` and `staff_chat_access`.
- **Vault reading:**
  - uploads go to `org-vault/<org_id>/…`;
  - `content_md` holds PDF text only, cut at about 24k characters;
  - xlsx files get no text;
  - no Import tool reads the vault.
- **Reusable pieces:**
  - `staff_sources.read_rows` / `browse`: openpyxl reading, redaction, cell citations, an LRU cache;
  - the pypdf page reading in `research_tools.read_document_pages`;
  - `FindingSourceType.org_document` and its precedence (6);
  - the synthetic-URL pattern `staff-sources.sangam.invalid/<id>`, and `hold_unmarked`;
  - the private-row mapping `_staff_dataset_rows` in `promote.py`.
- **Leaks that must close first:**
  - `save_research` publishes a brief that prints each finding's evidence word for word, and any signed-in user can open a brief. Staff spreadsheet evidence already goes there, and vault evidence would follow.
  - `GET /ingest/workbooks` and `select_source_files` accept any bucket.

### The leak rule this design keeps
Private text (vault or staff spreadsheet) must never sit in a model's context while that model can reach the web. `StaffLastLock` enforces this today by locking the web after staff rows are read. Vault reading goes to a **separate `vault-reader` subagent that has no web tools**. It saves its findings itself and hands back only ids and concept names. The web researcher then fills the gaps and never sees vault text.

## Architecture (target)
```
 browser (/import, role from /api/me)
    │ AG-UI + Supabase JWT
    ▼
 /ingest  ── chat_access (any signed-in user) ── sets ImportScope ContextVar
    │        staff  : all orgs, all funders, staff spreadsheets, delete
    │        steward: supported orgs (org_members.role='steward') + any funder
    │        member : any funder; own org's vault as a source
    ▼
 SUPERVISOR (Opus) — same graph; tools check the scope at call time and refuse outside it
    │ 1. task: vault-reader (when the user picked vault files)
    │ 2. task: entity-researcher ×N (web), told which concepts are still missing
    │ 3. task: catalog-writer (Review pause → save)
    ▼
 ┌──────────────── vault-reader (Haiku/Sonnet) ───────────────┐   ┌── entity-researcher (Sonnet) ──┐
 │ list_vault_documents · read_vault_document (PDF pages,      │   │ web tools + staff rows last     │
 │ xlsx cells) · research_goals · save_vault_findings          │   │ never sees vault findings       │
 │ NO web tools · scope-checked org · cites [vault:doc#p3]     │   │                                 │
 │ returns VaultSummary: concepts found / missing, doc ids     │   └────────────────────────────────┘
 └─────────────────────────────────────────────────────────────┘
    ▼
 entity_research (researched_by) + vault findings (own table, per org) ─► promote (scope check, vault → private documents row)
    ─► catalog, with promoted_by recorded ─► staff can delete research / undo a save
 Public brief: renders public-source findings only
```

## Stacked PRs

### PR A: close the leaks, and pass the caller to agent tools
- **`core/security.py`:**
  - a `chat_scope` ContextVar set beside `chat_user_id` in `chat_access`;
  - `ImportScope(user_id, is_staff, org_roles: dict[org_id, role])`, loaded once per request from `org_members` by a new `repositories/me.py` helper (or reuse the `/api/me` query);
  - helpers: `can_read_org(org_id)`, `can_save_org(org_id)` (staff, steward, admin or member of that org), `can_save_funder()` (any signed-in role), `is_staff`.
- **Brief** (`ingest/brief.py`): leave out findings whose `source_url` is a private synthetic URL (`*.sangam.invalid`). This applies to staff spreadsheets now and to the vault later.
- **`GET /documents`:** no change needed. It already runs as the caller, and the `documents_read` RLS policy limits it to public rows, the caller's orgs, or staff (`tests/test_rls.py`).
- **`/ingest/workbooks` and `staff_sources.check_pick`:** allow only the `staff-sources` bucket.
- **Tests:** a brief has no private evidence; any other bucket is refused; the scope is set per chat request.

### PR B: open Import by role
- **`core/lifespan.py`:** `/ingest` uses `chat_access` instead of `staff_chat_access`, and sets the scope.
- **`api/routes/ingest.py`:** drop the router-wide `require_staff`.
  - Staff only: `/sources`, `/proposals`, `/runs*`, `/queue*`, `/workbooks`.
  - `/research` lists, for anyone else, the rows they saved plus rows about the NGOs they steward. A summary written from private findings is replaced, as in the brief.
  - `/research/{slug}/review|coverage` read any slug; for anyone but staff, private findings (staff spreadsheets, later the vault) are removed before the view is built.
  - `/threads*` were already the caller's own.
- **Migration 0039 (changed from the first draft):** only `researched_by uuid`, the last person to save the row.
  - The row stays shared, one per entity per day, and `entity_research` stays staff-only under RLS. Per-user rows would have meant a "visible to this caller" filter in every reader (promote, coverage, review, dossier, brief). Filtering what each reader shows does the same job: staff spreadsheet findings already sit in shared rows today, so the fix had to live there anyway.
  - A non-staff caller cannot overwrite a row someone else saved today.
  - No steward write grant: agent tools use the owner pool, so RLS never gates a save. The tool checks are the gate.
  - `for_org_id` is dropped (see PR C), and `promoted_by` moves to PR D.
- **Supervisor tools enforce the scope at call time** and return a refusal string, as tools always do:
  - staff only: `list_storage_buckets`, `list_bucket_files`, `select_source_files`, `plan_import`, `run_import_now`, `pending_resolutions`, `record_registry_check`;
  - also `import_run_summary`, `read_workbook` and `publish_brief`;
  - `promote_research`: one slug at a time for non-staff; a funder needs a signed-in user, an NGO needs its steward (`can_research_org`), and a new NGO is staff's to add;
  - `save_research`: an NGO needs staff or a steward;
  - the researcher's `read_source_rows`: staff only;
  - with no caller (outside a chat request) a tool treats the run as nobody and refuses.
- **Prompt:** the `CallerNote` middleware appends a "who you are working for" line to the supervisor's system message on every model call, so it offers only allowed tasks. `_render` runs once at build time, so it could not carry this.
- **Frontend:**
  - `/import` reads `/api/me`;
  - `StartStep` shows cards by role: members get "Research a funder"; stewards get an org picker plus funder; staff see today's cards;
  - the Staff-only message in `ImportView` goes;
  - the Sidebar link stays.

### PR C: vault-reader
- **New `ingest/vault.py`:**
  - `vault_documents(pool, org_id)`: the org's private `documents` rows (`storage_path LIKE 'org-vault/%'`);
  - `read_pdf_pages(doc, pages)`: bytes from `storage.download`, then pypdf. Factor the page loop out of `research_tools.read_document_pages` and share it;
  - xlsx through `staff_sources.browse` / `read_rows`, generalised to take a document row instead of `list_source_datasets`. Redaction and cell citations are reused.
- **Citations:**
  - `source_url = https://org-vault.sangam.invalid/<doc_id>`;
  - markers `[vault:<doc>#p<page>]` or `[vault:<doc>#Sheet!B12]`;
  - `source_type = org_document`;
  - `evidence_tier = evidenced` for certificates and audited accounts, and `claimed` otherwise. The existing `check_tier` rules apply.
- **Tools** (`ingest/tools/vault_tools.py`): `list_vault_documents(org)` and `read_vault_document(doc_id, pages|sheet)`. Each checks `can_read_org` against the document's org. A member's own org is always allowed.
- **Subagent `VAULT_READER`** (`agent.py`):
  - tools: `list_vault_documents`, `read_vault_document`, `research_goals`, `save_research`;
  - the `filesystem(keep=read_file)` floor, and **no web tools**;
  - runs on the utility tier, with the research tier as fallback;
  - `response_format=VaultSummary(slug, concepts_found, concepts_missing, documents_read: list[int], fact_count)`. These fields are ids and enums only, with no free text, so no private wording reaches the supervisor;
  - prompt in `prompts/vault_reader.md`.
- **Vault findings in their own table, not merged into the shared row:** keyed by `(slug, researched_on, org_id)` and readable under org RLS. Merging them into `entity_research` would put one org's vault findings into another org's view of the same funder. Promotion takes the union of both for a caller allowed to read that org. `_staff_dataset_rows` is already the pattern for mapping private findings to a private `documents` row.
- **`promote.py`:** a vault URL maps to its existing private `documents` row (mirroring `_staff_dataset_rows`) and never goes through `ensure_document`, which would create a public row. Add `hold_unmarked` for a vault finding without its marker.
- **Supervisor instructions:** when the request names vault files, run the vault-reader first. Then launch the researcher with `concepts_missing` as its goals.
- **Frontend:**
  - Start: a "Use my organisation's documents" picker listing vault files from the filtered `GET /documents?org=`;
  - Working board: a vault-reader lane, with "Reading your documents".
- **Prompt and skill:** `ngo-credential-research/SKILL.md` "Doc Vault first" becomes accurate.

### PR D: saves by role, and staff delete
- **`promote_research`:** records `promoted_by`. A new `catalog_writes(promotion_id, table_name, row_id, action)` table logs each row written. The writer already returns what it wrote (the `saved` jsonb from 0038), so this extends it with ids.
- **Staff routes:**
  - `DELETE /ingest/research/{slug}`: remove saved research that was not promoted;
  - `POST /ingest/promotions/{id}/undo`: delete inserted rows and restore updated ones from the logged previous values, inside one transaction. Refuse when a row has changed since.
- **Frontend:** in Researched recently, staff get Delete and Undo save; each row shows who saved it.
- **Docs:** `docs/INGEST.md` gets roles, the vault-reader and the leak rule, and fixes the stale counts. CLAUDE.md and the README drop "auth is a stub". Add the feature plan `docs/features/2026-10-10-import-for-every-role.md`.

## Reuse
- `staff_sources.browse`/`read_rows`/redaction/`_cite` (`ingest/staff_sources.py`);
- `storage.download` (`integrations/storage.py:429`);
- the pypdf loop in `research_tools.read_document_pages`;
- `FindingSourceType.org_document` and `check_tier` (`research_records.py`);
- `_staff_dataset_rows` and `hold_unmarked` (`promote.py`, `staff_sources.py`);
- the `app.my_org_ids()` SQL helpers (`0024`);
- `chat_access` and the ContextVar pattern (`security.py`);
- the `StaffLastLock` reasoning (the vault-reader simply has no outbound tools).

## Verification
- **Unit:**
  - each scope can only call its allowed tools, and refusals come back as strings;
  - the vault-reader graph has no web tools (walk the compiled subagent, as `_subagent_tools` does);
  - `VaultSummary` has no free-text field;
  - one org's vault findings never appear in another caller's view of the same entity;
  - promoting a vault finding writes no public `documents` row;
  - the brief leaves out private evidence;
  - documents and research listings filter by role;
  - undo restores updated rows.
- **RLS integration** (`tests/test_rls.py` pattern): `entity_research` reads per role.
- **Live, local:** sign in as each role, using the member and steward seed users from `test_vault.py`.
  - **Member:** upload a grant-letter PDF, research that funder with the vault on, see vault findings plus web findings, save, and see `promoted_by`.
  - **Steward:** research a supported NGO; refused for an unsupported one.
  - **Staff:** delete and undo.
- **Checks:** pytest, ruff, tsc, lint, build.
