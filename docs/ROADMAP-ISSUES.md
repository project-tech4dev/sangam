# Proposed issues — data platform milestones

Drafted 2026-09-25 from the planning notes. Each entry is ready to paste into a
GitHub issue. **Read the "Already exists" column in the summary first** — most of
these extend working code rather than starting from scratch.

Owners as given in the notes: Apeksha, Siddhant, Vinod.

---

## Milestone 1 — Structured data in Postgres

### 1.1 Import CSR funder and CSO structured data from the tracking sheet
**Owner:** Apeksha

Load the structured funder/CSO records from the team spreadsheet into Postgres.

The target tables already exist and hold data: `orgs`, `funders`, `grants`,
`org_identifiers`, `funder_tags`, `funder_locations`. Current contents are 10
orgs, 4 funders, 14 locations, 40 tags — so this is an import that must merge
with existing rows, not a fresh load.

- [ ] Export the sheet to CSV and commit it under `seed/` so the import is reproducible
- [ ] Map each sheet column to a target column; list any with no home
- [ ] Decide the dedup key per table (`org_identifiers` holds Darpan IDs — likely the natural key for CSOs)
- [ ] Write the importer as an idempotent script, re-runnable without duplicating
- [ ] Record provenance: every scraped/extracted table has `source_url`, `source_name`, `fetched_at`, `content_hash`, `extractor_version` — populate them

**Open question:** the sheet almost certainly contains columns the schema has no
place for. Extending the schema is the decision this issue should surface, not
silently drop them.

**Blocked on:** sheet access. The Google Sheets link in the notes is private.

---

### 1.2 Decide schema extensions for CSR-specific funder fields
**Owner:** Apeksha + Siddhant

The rubric work (4.1) needs funder **program**, **focus area**, and **grant
size**. `funders` and `grants` cover some of this; grant size ranges and
programme structure may not have a home yet.

- [ ] Audit which of program / focus area / grant size are already representable
- [ ] Design the additions (new columns vs. a `funder_programs` table)
- [ ] Write a migration in `db/migrations/` — do not edit `02_schema.sql`, it is the baseline for new databases

**Depends on:** 1.1 (need the real column list first)

---

## Milestone 2 — Unstructured data and embeddings

### 2.1 Object storage for source documents
**Owner:** Siddhant

Raw funder PDFs, annual reports, and scraped pages need durable storage. The
notes say S3.

- [ ] **Decide S3 vs. Supabase Storage.** Supabase is already provisioned and paid for; S3 is another account, another credential, another bill. Supabase Storage is S3-compatible.
- [ ] Define the key layout (`funders/<slug>/<content_hash>.pdf` or similar)
- [ ] Store the object key on `documents` so a row points at its source file
- [ ] Backfill the existing 96 documents where the original file still exists

**Note — likely already broken in production:** the agent's `download_file` and
`read_pdf` tools write to a local `downloads_dir`. The backend now runs as a
Vercel Function, where each invocation gets a fresh filesystem, so downloaded
files vanish between calls. This issue fixes that, not just archival.

---

### 2.2 Chunk and embed documents into pgvector
**Owner:** Siddhant

**The schema is already in place and empty.** `chunks` exists with
`document_id`, `chunk_index`, `content`, a generated `content_tsv` for
full-text, and `embedding vector(1536)` — sized for OpenAI. It has **0 rows**.

- [ ] Write the chunking pipeline over `documents.content_md`
- [ ] Embed with OpenAI (`text-embedding-3-small` is 1536-dim, matching the column)
- [ ] Backfill all 96 documents
- [ ] **Add a vector index** — there is currently no `hnsw` or `ivfflat` index, so every similarity query is a sequential scan. Fine at 96 documents, not at 10,000
- [ ] Make re-embedding idempotent, keyed on `documents.content_hash`

**Depends on:** nothing. This can start today.

---

### 2.3 Hybrid search tool for the agent
**Owner:** Siddhant

`chunks.content_tsv` (keyword) and `chunks.embedding` (semantic) together
support hybrid retrieval. Expose it as an agent tool alongside the existing
`search_orgs` / `get_funder` / `get_grants` / `get_fit_scores`.

**Depends on:** 2.2

---

## Milestone 3 — Knowledge graph

### 3.1 Decide whether Neo4j stays
**Owner:** Vinod + Siddhant — **discuss before building**

The graph is built but dormant: Graphiti + Neo4j are wired up, 29 episodes were
ingested on 2026-09-21, and `search_graph` is a registered agent tool. But
`NEO4J_URI` is unset, so `graph_enabled` is false and the tool currently returns
"graph unconfigured." Nothing in the deployed stack uses it.

Before investing further, settle:

- [ ] What questions does the graph answer that `chunks` + pgvector cannot? Multi-hop relationship traversal is the honest answer — confirm the product needs it
- [ ] Hosting: Neo4j Aura is a third database to run and pay for
- [ ] **Embedding dimension conflict.** `docs/DEPLOY.md` specifies `EMBEDDING_DIM=768` to stay compatible with the existing graph, but `chunks.embedding` is `vector(1536)`. Two different embedding spaces across two stores. Either reconcile them or accept the split deliberately

**This is the "discuss with Vinod" item — it is a decision issue, not an implementation issue.**

---

### 3.2 Model org ↔ funder entity relationships in the graph
**Owner:** Vinod

Build the entity-relationship layer: which funders fund which orgs, through
which programmes, over what periods.

Postgres remains the system of record and the graph is rebuildable from it (see
`seed/graph_seed.py`) — keep that property.

- [ ] Define the node and edge types
- [ ] Decide how temporality is handled (Graphiti is bitemporal; `grants` already has valid_from/valid_to style columns)
- [ ] Extend `graph_seed.py` to build relationships, not just episodes

**Depends on:** 3.1 — do not start until the graph's future is settled

---

## Milestone 4 — Funder ↔ CSO matching rubric

### 4.1 Extend the rubric to program / focus area / grant size / geography
**Owner:** Apeksha + Vinod

**A rubric system already exists and has been used.** Two versions are loaded:
v1 (7 criteria, 100 points) and v2 (7 criteria, 14 sub-criteria, 100 points),
with 88 rows of actual scores in `fit_score_items`. The registry UI already
shows "Scored against rubric v1, v2."

The notes propose scoring on funder program, focus area, grant size, and CSO
geography. So the work is:

- [ ] Audit v2's 22 criteria against the four proposed dimensions — how much is already covered?
- [ ] Add what is missing as **rubric v3** rather than mutating v2, so historical scores stay interpretable (`rubrics` is already versioned, and `rubric_criteria` supports parent/child via `parent_id`)
- [ ] Define the scoring rule per new criterion — grant size and geography can likely be computed rather than LLM-judged
- [ ] Decide whether to re-score existing pairs against v3

---

### 4.2 Automate fit scoring
**Owner:** TBD

Scoring today appears to be manual or one-off. Make it a repeatable job over
funder × org pairs, writing `fit_scores` and `fit_score_items` with
justifications.

**Depends on:** 4.1

---

## Milestone 5 — Agent query layer

### 5.1 Agent tools for the new data
**Owner:** Siddhant

The agent already has `search_orgs`, `get_funder`, `get_grants`,
`get_fit_scores`, `search_graph`, `fetch_url`. As the data layer grows it needs:

- [ ] Hybrid document search (2.3)
- [ ] A matching/recommendation tool over `fit_scores` ("which funders fit this CSO and why")
- [ ] Graph traversal, if 3.1 says the graph stays

**Note:** the notes ask "Postgres or pgvector" — these are not alternatives.
pgvector is an extension *inside* the Postgres you already have, installed and
running on Supabase (v0.8.2). There is no separate system to choose.

---

## Cross-cutting — not in the notes but blocking

### X.1 Supabase Auth to replace the stub user
**Owner:** Siddhant

The deployed backend has no authentication and is publicly reachable.
`backend/app/auth.py::get_current_user` resolves every request to one stub user.
`db/init/03_dev_user.sql` already names the intended fix: "until Supabase JWT
auth replaces `backend/app/auth.py::get_current_user`."

Every route already does `Depends(get_current_user)`, so the backend change is
one function plus a user-provisioning upsert (`threads.user_id` has a foreign
key to `users`, and Supabase identities will not exist there on first login).
The frontend has five hardcoded `Authorization: Bearer dev` call sites.

**Do this before the URL is shared outside Tech4Dev** — until then anyone who
finds it can read all grant data and spend the Anthropic key via `/agent`.

---

### X.2 Merge `fix/vercel-deploy-readiness`
**Owner:** Siddhant

Both Vercel projects run branch code while `master` lags. A push to `master`
would deploy something older than what is live.
