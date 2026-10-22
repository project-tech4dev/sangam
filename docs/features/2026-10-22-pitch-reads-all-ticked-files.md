# Sangam Pitch reads every file it lets you tick

## In plain words

Step 2 shows you every file Sangam holds for the org, but Pitch can only open files you uploaded yourself
(PDF/Word/Excel). Most of the list is web pages that Import saved, as `.md` text or PDF, plus some web links
with no saved copy. We teach Pitch's file reader to open those too, and stop it collecting every page it has read
in its memory.

Example: you tick `satra-annual-reports-summary.md` (doc 206). Today the reader says "no readable file". After the
change it reads the page 24k characters at a time, saves facts like "1,240 households…" cited to
`raw.githubusercontent.com/…`, and tells the chat "read, 12 facts".

## Where `.md` comes in

```
 Pitch chat ─ read_files ─► code launches one reader per ticked file
                               │
                               ▼
                     file reader ── read_org_file(id) [NEW: one tool, picks the right opener]
                                        │
          ┌─────────────────────────────┼──────────────────────────────┐
          ▼                             ▼                              ▼
   your Doc Vault upload         Import-saved public copy         link only, no copy
   org-vault/…pdf|docx|xlsx      source-archive/…md|pdf|docx      (just a URL)
   vault.read  (as today)        _archived  [NEW .md/.txt →       [NEW, M2] code fetches the URL
                                   numbered lines, 24k a window]    once, saves it to source-archive,
                                                                    then it reads like the middle box
          │                             │                              │
          └──── facts: origin "vault" ──┴── facts: origin "web", cited to the page's real link ──┘
                                        ▼
                         add_facts → proposal's fact list (database)
```

### Yes: one subagent per file, and how a long `.md` stays small

- **One subagent per ticked file.** These are the existing file readers (`proposals/readers.py`); we add no new
  agent. Code launches them, not the chat model, so there is no `task` tool. They run at the same time, up to
  `MAX_PARALLEL_RESEARCH` (8). Each runs on `RESEARCH_MODEL` (Sonnet) with its own empty context and no checkpoint.
  - Example: tick 4 SATRA files → 4 readers run side by side, plus the funder reader.
- **The chat (Opus) never holds a file.** Each reader ends with a 3–4 line note ("SATRA annual reports summary: 12
  facts added; no budget figures"). Only that note returns to the chat. The facts go straight to the database.
- **A long `.md` is read in windows, not at once.** Take a 90,000-character dossier:
  1. `read_org_file(206)` returns lines 1–~400 (≤24k chars, ~6k tokens) and ends "cut at line 400 of 1,650; call
     again with start_page=401".
  2. The reader saves what it found with `add_facts` (≤15 per call), then reads from line 401, and so on: 4 windows
     in all.
  3. **[NEW]** Once the reader's context passes 60k tokens, `clear_old_tool_results` replaces the oldest windows with
     a placeholder and keeps the last 5. Their facts are already saved, so nothing is lost, and each step stops
     re-sending pages the reader has finished with.
- **Worst case, one subagent:** a 150-page report is ~25 windows. Without clearing, the later steps each re-send
  ~150k tokens; with it, about 60k at most. Other readers are unaffected, because each has its own context.

`.md` enters at **one function**, `_archived` (`ingest/tools/library_tools.py:73`). Today it handles PDF (by page)
and Word (by paragraph). We add a third case: plain text and markdown, read by line. Because that function is shared,
the same change also lets Import's library reader and Pitch's funder reader open `.md`.

## Context

Langfuse shows every file reader on SATRA → Axis Bank Foundation (2026-10-22, three runs) and KABIL → EdelGive
(2026-10-21) ending `UNREADABLE`. Production data says why: step 2 lists **every** `documents` row linked to the org
(`repositories/documents.py:15`), but the file reader holds one tool, `read_vault_document`, which only opens private
`org-vault/` PDF/DOCX/XLSX (`ingest/vault.py:63,140`). Of 142 org-linked files in production Pitch can read 8:

| Kind | n | Example | Today |
|---|---|---|---|
| Public page Import archived as `.md` (`source-archive/`) | 85 | doc 206 `satra-annual-reports-summary.md` | ❌ |
| Public page saved as a link, no copy | 26 | doc 207 GuideStar, satra.ngo annual report | ❌ "upload the file" |
| Public PDF archived (`source-archive/`) | 22 | | ❌ |
| Doc Vault PDF/DOCX | 8 | | ✅ |
| Doc Vault PNG | 1 | doc 259 `AI Toolkit .png` | ❌ (stays out of scope) |

Outcome: the first 111 + 22 read, each fact cited to the page's real `source_url`; an image or a page the site refuses
still fails with a one-line reason. That leaves so few unreadable files that step 2 gets no "can't be read" label
(dropped from my earlier suggestion). A Doc Vault `.md`/`.txt` upload gets the same text branch in `vault.read`, for
consistency (production has none today).

## How reading works, and why it doesn't overload context

```
 Pitch chat (MODEL, Opus)  ── read_files ──►  code: readers.read()  (no model; one lock; status per file)
   sees only each reader's                      │ asyncio.gather, ≤ MAX_PARALLEL_RESEARCH at once
   3–4 line closing note                        ├─► file reader #206 (RESEARCH_MODEL, own context, no checkpoint)
                                                │     read_org_file(206, start_page=1) → ≤24k chars
                                                │     add_facts(≤15) … read_org_file(206, start_page=N) … add_facts
                                                │     [NEW] clear_old_tool_results: past 60k tokens keep last 5 reads
                                                ├─► file reader #41 (vault PDF — unchanged path)
                                                └─► funder reader (unchanged)
                              facts ──► proposals.work.facts (database), never the chat
 [NEW] link-only doc: code fetches source_url once (check_url + guarded client), archives it, then a reader reads it
```

- **The chat never sees a file.** `read_files` runs the readers in code (`proposals/readers.py:_one`); each reader is
  its own deep agent with its own context. What returns to the chat is `"<title>: read.\n<closing note>"`, which the
  prompt keeps to three or four lines. Facts go to the database through `add_facts`.
- **A reader sees a file one window at a time.** Every read is cut at `MAX_CHARS = 24_000` (~6k tokens) and says
  "call again with a later start_page" (`vault.py:24`, `library_tools.py:88`). The new `.md` reader keeps that rule,
  windowing by line instead of page.
- **The gap today:** a reader's own context keeps every window it read (`evict=False`, no clearing). A 150-page
  annual report is ~25 windows ≈ 150k tokens, all re-sent on every step. The fix adds the existing
  `clear_old_tool_results()` (`agent/middleware.py:186`: triggers at 60k tokens, keeps the last 5 results) to the
  readers. That's safe because the prompt already has the reader `add_facts` in batches as it goes, so a cleared
  window's facts are already saved. Overflow itself is covered by `fallback`; the gap is the token bill.

## M1 — PR 1: read archived public files, `.md` included

1. **`.md`/`.txt` in `_archived`** (`ingest/tools/library_tools.py:73`). Add `.md` and `.txt` to `READABLE`.
   Plain text becomes numbered lines; `start_page` counts lines; each window holds ≤ `MAX_CHARS` and its lines carry
   `[line N]`. The header says "Quote the sentence; say which line", like the page/paragraph cases. This also fixes
   Import's `read_library_document` and Pitch's `read_funder_document`/`read_template` for `.md`. Blast radius:
   Import's `list_library_documents` (`library_tools.py:63`) now labels archived `.md` pages "archived copy" rather
   than "link only", so Import researchers will read them instead of re-fetching.
2. **One file tool for the reader: `read_org_file`** (new, `proposals/tools/reading_tools.py`), replacing
   `read_vault_document` in `EVIDENCE_TOOLS` (`proposals/agent.py:44`). It takes the same arguments.
   - If the id is the org's own vault file, it calls `vault.read` (unchanged).
   - If it's a public `source-archive/` row with `org_id = p.org_id`, it reuses `_public_file(document_id, "AND org_id = %s", …)`.
   - Anything else gets "not one of the files ticked for this proposal".
   - Add the name to `run_sources.VAULT_TOOLS` and the per-document check (`run_sources.py:83`), so `RunSources`
     refuses any id outside `vault_docs`: the one file the reader was given. Rename the check to cover both
     names; no new `Sources` field.
3. **`evidence_reader.md`**: a vault file → `origin "vault"` with its `[vault:…]` marker (unchanged). A public page →
   `origin "web"`, `source_url` the link the read printed, quoting the sentence (`facts.py:96` already validates
   this, as the funder reader uses it).
4. **`clear_old_tool_results()`** in `readers.build.reader()` middleware (evidence and funder readers).
5. `readers._titles` keeps the link detection (`storage_path` empty) for M2; label stays "a file".

Tests (unit, no DB): `_archived` on a `.md` gives `[line N]` windows and the cut notice; `read_org_file` routes vault
vs public and refuses another org's document (monkeypatched repository); `RunSources` refuses `read_org_file` on a
non-ticked id; the existing "every tool named in its prompt" and subagent tool-list tests updated.
Exit gate: SATRA's docs 205/206/208 and 204 read with facts on the local stack (below).

## M2 — PR 2 (stacked): fetch a link-only file once, then read it

1. In `readers._one`, replace the link short-circuit (`if link: … "upload the file"`). Code (not the model) fetches
   the row's `source_url`, choosing by content type:
   - a page through `research_tools._read_page`, which archives `.md` and handles JSON and plain text;
   - a PDF or Word file through `_fetch_document`.
   Both already run `check_url` (registry + robots) and `guarded_client`. Then
   `storage.archived_key(SOURCE_ARCHIVE, url)` → `UPDATE documents SET storage_path, content_hash, fetched_at
   WHERE id = %s AND storage_path IS NULL`, and the reader reads it as in M1.
   - The reader still gets no web tool, and the org's own known URLs are fetched; no search is made.
   - `check_url` (`ingest/access.py:25`) and `_client` don't read `run_sources.CURRENT`, so a direct call from code
     works under the reader's `Sources(web=False)`; it is a code path, not a tool call.
   - **New write path:** Pitch updates `documents` on the owner pool, gated by `require_edit` in `read_files`. That's
     the same posture as Import's writes. The UPDATE also sets `extractor_version` (a provenance column).
2. Refused, an HTTP error or no text gives a failed row with one short reason ("the site refused it: HTTP 403").
   "Try again" retries it as today.

Tests: link doc → fetch stubbed → row updated → reader runs; a refusal from `check_url` → failed with reason, no
update; an already-archived row is not fetched again.
Exit gate: doc 207 (GuideStar JSON) and a satra.ngo annual report PDF read locally. Storage is global: this local
run uploads the archived copies to the shared `source-archive` bucket, as every local Import run does already; the
Postgres rows stay local.

## Docs

ARCHITECTURE.md (Pitch section): readers open vault files and the org's public archived files; links are fetched
once by code. CHANGELOG line per PR. `make wiki-update`. Plan committed as `docs/features/2026-10-22-pitch-reads-all-ticked-files.md`
on the feature branch before code.

## Verification

- `cd backend && pytest tests -k "proposal or library or vault or run_sources" && ruff check .`; full `pytest -m "not integration"`.
- Local stack only (shared Supabase rows are never written). The local DB has no `source-archive` org rows, so copy
  the SATRA rows 204–208 (metadata only; the objects live in the shared Storage bucket and are only downloaded) into
  the local `documents` for a local SATRA org. Then in the browser: open a SATRA → Axis Bank Foundation proposal,
  tick them, and press "Write the first draft". Every row should show read, and facts should cite `give.do`/`raw.githubusercontent.com` links.
- Langfuse (environment `local`): the `sangam_proposal_reader` traces end without `UNREADABLE`. In a long file's trace,
  old `read_org_file` results show as cleared after 60k tokens.
