# Sangam data platform: storage, retrieval, access and matching

Status: design for review, 2026-09-27. It builds on the proposals in `features-plans/` (prototype-v1 and the v3 data model), which are still under review. This spec does not move those files into `db/` or `seed/`, or change migration and seed paths; that happens when v3 is accepted.

## 1. Decision

| Concern | Decision |
|---|---|
| System of record | Postgres (v3 model once accepted) |
| Authorization | Postgres row level security (RLS), applied to **every** backend and agent query by running each request as the caller |
| Document retrieval | pgvector plus full text over `chunks`, merged with rank fusion; chunks inherit their document's access rule |
| Matching | SQL views and functions over typed tables |
| Connection questions ("how are KABIL and Axis connected") | An `entity_edges` view plus a `connections()` function in Postgres |
| Name resolution | Fixed identifiers, then aliases and `pg_trgm` similarity, then an LLM tie-break, with a human review queue |
| Graphiti + Neo4j | **Deferred.** Not on the critical path. See section 9 for when to revisit |

## 2. Evidence

Two throwaway spikes were run on 2026-09-27 against the v3 schema and seed data. The files are in the session scratchpad, not the repo.

**Spike 1: SQL vs Cypher over typed data** (8 matching and connection questions, same data):

- Both engines gave the same core answers once they read the questions the same way.
- Cypher was about 2.6x shorter for traversal: 183 lines against about 480. Much of the SQL length was a four-way union of org places, repeated in every file, which one view would remove.
- Every query ran in milliseconds on both engines.
- A naive 5-hop Cypher path query took 12 s because of the Axis hub node; a hand-written rewrite took 0.2 s. SQL took 18 ms.
- Match quality was limited by **data gaps**, not by the engine (section 8).

**Spike 2: Graphiti on real text** (48 episodes from 3 Axis CSR reports and 4 news articles, Claude Haiku 4.5, local embeddings, about $23 in total):

- It merged spelling variants well and found 51–54 of 55 known partners.
- About 3% of edges were attached to the wrong node. It merged Christian Medical College, Vellore into the registry org Better Life Foundation.
- An unlinked "Axis Bank" node took 298 edges, against 49 on the seeded "Axis Bank Limited".
- It expired per-year facts as if the next year had replaced them. All 14 partnership expiries in the plain run, and 39 of 40 in the typed run, were wrong.
- It answered 0 of 4 benchmark questions as well as SQL: theme shift over years, Assam livelihood partners, partners renewed every year, and the KABIL–Axis connection. Its search returns single facts and cannot aggregate.

Conclusion: at Sangam's scale (about 50 orgs and 100 funders across the North East and Pune, roughly 100k typed edges), Postgres answers every benchmark question with sources and access control. Graphiti's one clear strength, fuzzy name resolution, costs far less to build in Postgres, and there it can be reviewed.

## 3. Architecture

```
browser ── Next.js ── CopilotKit ── FastAPI /agent (LangGraph)
                                     │  every request: verify JWT → user
                                     │  every DB transaction: run as caller (RLS applies)
                                     ▼
                         Postgres + pgvector (Supabase)
             typed registry · matching views · documents/chunks
             entity_edges · name-resolution queue · threads/checkpoints
```

There is one store. Neo4j stays in docker-compose as an optional service for now. The agent does not depend on it (section 9).

## 4. Authentication

- The frontend signs in with Supabase Auth (Google). It sends the access token as `Authorization: Bearer` to REST and, through the CopilotKit runtime, to `/agent`.
- `backend/app/auth.py:get_current_user` verifies the JWT against the Supabase JWKS and returns `sub`. The user is resolved as `users.auth_user_id = sub`, and a `users` row is created on first sign-in.
- Anonymous callers are allowed on public routes and get the `anon` role.
- Local dev: `03_dev_user.sql` gives the dev user a fixed `auth_user_id`, and a `DEV_AUTH=1` flag makes the backend accept the dev token. Also fix the stale path in that file's comment.

## 5. Authorization

### 5.1 Mechanism: run every query as the caller

The backend connects as the table owner, so it bypasses RLS today. The v3 plan was to repeat the RLS filters by hand in each query ("Still needed" rows 1–2), which will break the first time someone forgets a filter. Instead, each request's transaction starts with:

```sql
SET LOCAL ROLE authenticated;          -- or anon
SELECT set_config('request.jwt.claim.sub', :auth_user_id, true);
```

`auth.uid()` (the local stub, and Supabase's own) reads that setting, so every v3 policy applies unchanged to REST endpoints and agent tools. This is done in one helper, e.g. `db.user_conn(user)`, which every repository and tool must use. A test fails if any module uses the pool without that helper.

The prerequisites below apply to the local container. Supabase already provides these grants.

- `GRANT anon, authenticated TO <owner role>`, so the owner can `SET ROLE`.
- `GRANT SELECT` (plus the needed `INSERT`/`UPDATE`) on public tables to `anon` and `authenticated`. v3 only grants usage on schema `app`.

### 5.2 Threads

`/agent` calls `app.can_open_thread(thread_id, user_id)` before it loads or writes LangGraph checkpoints. It returns 404 when the call returns false. The checkpoint tables have no RLS path, so this check is their only protection.

### 5.3 Tables created by tooling

Enable RLS on `schema_migrations`, `graph_ingest_log` and the LangGraph checkpoint tables when they are created, with no policies, so the Supabase API can't read them.

### 5.4 Document granularity

v3 access is per org: a private document is visible to the org's `admin`, `member` and `steward` users, and to staff. That is enough for now. If per-file control is needed later, add `documents.visibility` with values `org`, `org_admins` and `org_members_only` (members and admins, no stewards), and extend `documents_read`. Chunks follow automatically.

## 6. Document retrieval

- **Pipeline:** documents are chunked at about 1,000 characters with overlap, keeping `document_id`, `chunk_index` and page. Each chunk is embedded. When `content_hash` changes, the old chunks are replaced (the v3 rule).
- **Embeddings:** OpenAI `text-embedding-3-small`, 1536 dimensions. This matches `chunks.embedding vector(1536)` and the draft Terms, which name OpenAI as the embeddings vendor. Add an HNSW index (`vector_cosine_ops`). Remove the 768-dimension `EMBEDDING_DIM` setting that only served the graph.
- **Search:** pgvector top-k and `content_tsv` top-k, merged with reciprocal rank fusion. The function takes `funder_id`, `org_id`, `doc_type` and fiscal-year filters, and runs under RLS as the caller.
- **Agent tool:** `search_documents(query, funder?, org?, doc_type?, fiscal_year?)` returns passages with `[doc:ID p.N]` citations.

## 7. Typed extraction, name resolution, matching, connections

### 7.1 Typed extraction

Reports go into the v3 tables, each row with its source (as in the Axis load): themes, footprints, partners, CSR years, CSR spend and metrics. Facts that drive matching are always typed rows, never free-text facts. The SQL seed generator the v3 doc says is missing goes into the repo.

### 7.2 Name resolution

For every extracted org, funder, partner or place name, try these in order:

1. **Fixed identifiers:** CSR-1, PAN, Darpan ID, CIN, LGD code.
2. **Exact match** on name or alias, case-insensitive.
3. **`pg_trgm` similarity** over names and aliases, above a threshold.
4. **LLM tie-break** among the top 3 candidates, given the context.
5. **Review queue** (`resolution_queue`) for anything below the confidence cut-off.

A new name is never merged automatically into a registry org without passing step 1 or 2, or a reviewer. This rule prevents the hospital-into-NGO merge from Spike 2. Accepted variants are written back to `aliases` or `partner_canonical`. This step also fills `funder_partners.org_id` and `funder_csr_spend.agency_org_id`.

### 7.3 Matching

These views and functions replace the four-way union that every spike query repeated:

- **`org_places`:** an org's places from `org_locations`, the registered location, `program_locations` and `grant_locations`, rolled up to district and state.
- **`org_tag_set`:** the org's tags plus its programmes' tags (decision 4), expanded one hop through `meta.maps_to`.
- **`funder_signal_base`:** a funder's own rows plus its parent's rows (decision 1).
- **`match_scores(org_id)`:** a transparent score with one column per signal.

| Signal | Weight (to be tuned) | Rule |
|---|---|---|
| Place | 25 | Recent footprint in the org's district = 1; in the org's state = 0.5; stated priority (`funder_locations` with role `priority`) = half of the matching footprint value (decision 3) |
| Theme | 20 | The funder's CSR sectors (through `maps_to`) overlap `org_tag_set` |
| Priority | 15 | The org's place is designated (aspirational district, North East) and the funder's theme has the matching `geo-*` tag |
| Partner fit | 10 | The funder's resolved partners share a district or tag with the org; renewal rate |
| Grant history | 15 | The funder has funded this org, or orgs similar to it; recent grants weigh more (decision 2) |
| Size | 15 | Latest prescribed CSR amount, normalised |

**Eligibility gate (decision 5):** if the funder is bound by Section 135 and the org's CSR-1 status is `not_available`, `not_found`, `cancelled` or `expired`, the match returns `blocked: csr1` with a "fix CSR-1 first" action instead of a score. Funders not bound by Section 135 are not gated.

### 7.4 Connections

- **`entity_edges`:** a view of (`src_type`, `src_id`, `rel`, `dst_type`, `dst_id`, `fiscal_year`, `document_id`) over grants, footprints, partners, parent links, place and tag links, and later the reviewed text facts.
- **`connections(a, b, max_hops => 3)`:** a recursive search that prunes hub nodes (country and state nodes, and nodes above a degree cap, are only allowed as endpoints). It returns the direct links and the shortest evidenced paths.
- **Agent tool:** `get_connections(a, b)`.

Example answer for KABIL and Axis:

- **Funding:** KABIL → grant → Axis Bank Foundation → parent → Axis Bank Limited.
- **Place:** Axis's Education and Lives & Livelihoods themes ran in Udalguri in FY24-25 and FY25-26.
- **Priority:** Udalguri is an aspirational district in the North East.
- **Partners:** no shared partners yet.

## 8. Data gaps to fix before matching is meaningful

Both spikes found these:

1. `seed.py` files Dimapur, Tamenglong and Bishnupur under Assam, which creates duplicate districts and loses matches.
2. `funder_partners.org_id` is never set (fixed by section 7.2).
3. `grant_locations` and `program_locations` are empty.
4. KABIL, BDF and the other orgs have only free-text theme tags, with no taxonomy mapping.
5. Only Axis has theme programmes, footprints and CSR years; the other funders need the same extraction.
6. Credential history is mostly not seeded, and `credential_status` leaves out credentials that have no events. ABF's `section_135_applicable` looks wrong.
7. `fiscal_year` is text, and `meta.designation` is joined by text. Accept both for now, with a check constraint on the `FYyyyy-yy` format.

## 9. Graphiti and Neo4j: deferred

- **Now:** `search_graph` passes `group_ids=['sangam']` and nothing private is ingested; or the tool is removed. `graph_seed.py` is not rewritten. The Neo4j service is optional in compose.
- **Revisit** when one of these holds:
  - There is a large public narrative or news corpus, and the questions need relationships found only in that text.
  - Connection or graph-algorithm queries over `entity_edges` get too slow or too hard to write in SQL.
- **Conditions if revisited:**
  - Public text only.
  - Registry nodes seeded, with merges anchored to them.
  - Automatic fact expiry turned off or customised.
  - Access only through a backend wrapper that sets `group_ids` from `org_members`. Never expose the Graphiti MCP server directly.
  - Neo4j as a read-only copy loaded from `entity_edges` (the spike loaded the whole typed graph in 2.4 s).

## 10. Testing

- **RLS:** for each role (anonymous, stranger, member, steward, staff), check which private documents, chunks, identifiers, unvetted news and threads it sees, through the **backend**, not just psql. Reuse the v3 test cases.
- **Guard:** a test fails if any module queries the pool without `user_conn`.
- **Retrieval:** golden questions with expected document ids; private chunks never appear for non-members.
- **Matching:** golden outputs for KABIL and BDF, including the CSR-1 gate and the parent roll-up.
- **Name resolution:** a labelled set (Peepul / Peepul Trust, CMC vs Better Life Foundation, the Axis variants) that measures precision and recall. Wrong automatic merges into registry orgs must be 0.

## 11. Suggested build order

1. Authentication (section 4) and running each request as the caller, plus the thread check (section 5).
2. The document pipeline and `search_documents` (section 6).
3. Name resolution and the data-gap fixes (sections 7.2 and 8).
4. The matching views and `match_scores` (section 7.3).
5. `entity_edges` and `connections()` (section 7.4).

Each step gets its own implementation plan.

## 12. Decisions taken

These were recorded on 2026-09-27, using the recommended options:

1. A foundation inherits its parent company's matching data in full.
2. Grant history is a sixth scoring signal, with recent grants weighted more.
3. Stated priority places count at half the weight of an actual footprint.
4. An org's tag set includes its programmes' tags, and free-text tags are mapped to the taxonomy.
5. CSR-1 `not_available` blocks matches with Section 135 funders only.

## 13. Out of scope

- Moving the v3 files into the repo layout, and updating migration and seed paths (deferred until v3 is accepted).
- UI work from prototype-v1: the left rail, structured answer cards and mobile layout.
- Pulling data from csr.gov.in (needs an Indian network).
