# Funder pool: a model decides close names

Draft v1, 2026-11-28. Status: plan only, no code yet.

## 1. Goal

**When a pool funder's name is close to a funder Sangam already holds, a model searches and decides whether
they are the same, instead of parking the row for a person.**

Success, measured on the next 45-funder batch:

| Measure | Last batch (27–28 Nov) | Target |
|---|---|---|
| Rows parked as "a close name in Sangam" | 13 of 195 | 0 |
| Wrong merges (a SAME that a person rejects) | — | 0 |
| Cost of a check | — | under $0.10 |

All 13 parked rows last time were different companies:

| Pool funder | Matched to | What they share |
|---|---|---|
| Oil India | Indian Oil Corporation | "oil" |
| ICICI Bank, IDBI Bank, South Indian Bank | HDFC Bank | "bank" |
| Western Coalfields | Northern Coalfields | "coalfields" |
| Mankind Pharma | Gland Pharma | "pharma" |

A person would have answered "different" 13 times out of 13. A model with a web search answers that in seconds.

## 2. Blast radius

Built by hand from `backend/app/ingest/pool/` and the `resolution_queue` constraints. Nothing outside the pool path changes.

| Surface | Hop | Why affected | Status |
|---|---|---|---|
| `ingest/pool/job.py` | 0 | the close-name branch (`job.py:60`) calls the check instead of parking the row | in scope |
| `ingest/pool/identity.py` (new) | 0 | builds the check and returns its decision | in scope |
| `ingest/pool/worker.py` | 1 | builds the check once, lazily, beside `Scout` | in scope |
| `resolution_queue` | 1 | the decision is stored here as `accepted` / `rejected` / `pending`, with the reason in `notes`; no migration | in scope |
| `core/config.py` | 1 | one setting, `POOL_IDENTITY_MODEL`, with `off` as the switch back | in scope |
| `tests/test_architecture.py` | 1 | `identity.py` imports Scout's search tools, so it joins `BUILDERS` (rule R1) | in scope |
| Import "Waiting for you" | 2 | shows fewer pool questions; only UNSURE rows still appear | unchanged code |
| `catalog/matcher.py` | 2 | still finds the candidates; its scoring is unchanged | out of scope |
| Scout chats, Review, `promote.py` | 2 | their close-name step is not the pool's | out of scope |
| SQL catalog, Ask, frontend | — | no table, column or route changes | not affected |

## 3. High-level design (HLD)

```
worker.tick ─► job.process(row)
                 │ resolve_funder(name, cin, website)
                 ├─ exact / alias / CIN / boilerplate ─► skipped (as today)
                 ├─ a person already answered        ─► as today
                 └─ close name, nobody answered
                        │
                        ▼
              ┌─ NEW identity check ────────────────────┐
              │ deep agent, RESEARCH_MODEL (Sonnet)     │
              │ tools: search_public_sources, read_page │
              │ in:  pool row + candidate funder rows   │
              │ out: SAME | DIFFERENT | UNSURE,         │
              │      funder_id, reason, source_urls     │
              └─────────────────────────────────────────┘
                        │
         SAME + cited ──┼─► resolution_queue accepted ─► skipped, funder_id set
         DIFFERENT ─────┼─► resolution_queue rejected ─► research as its own funder
         UNSURE / error ┴─► resolution_queue pending  ─► research as its own funder
```

> **The rule:** only a cited SAME merges. Everything else is researched as a new funder.
> **Example:** Oil India against Indian Oil. The model finds oil-india.com and says DIFFERENT, so Scout
> researches Oil India as its own funder, as it would have after a person said "No, they're different".
> **Why it matters:** a wrong merge puts one company's CSR spend on another's profile, while a duplicate is cheap to fix.

UNSURE stays `pending`, so a person still sees it under "Waiting for you". Research goes ahead either way,
and pool research waits for Review before it reaches `funders`, so no duplicate funder row is created.

**Trade-off.** A separate check at this point, not a question inside the researcher's task: the pool stops
*before* research when it finds a close name (`job.py:60`), so there is no researcher yet to ask. The check
reuses Scout's two search tools and the news verifier's shape (`ingest/news/verify.py`), so nothing new is
invented.

Touches Postgres (`resolution_queue`, `funder_pool`, as today) and the model plus Tavily. No Neo4j, no Storage.

## 4. Low-level design (LLD)

**`backend/app/ingest/pool/identity.py`** (new, about 80 lines), shaped like `ingest/news/verify.py`:

```python
class Decision(BaseModel):
    decision: Literal["SAME", "DIFFERENT", "UNSURE"]
    funder_id: int | None = None
    reason: str = ""          # trimmed to 300 characters
    source_urls: list[str] = []

def build_identity_check(settings) -> Any:   # create_deep_agent + harness, response_format=Decision
async def decide(agent, row, candidates) -> Decision:   # never raises; an error is UNSURE
```

- Tools: `search_public_sources` and `read_page`, plus the harness's `read_file` floor. No subagent, no checkpointer.
- Limits as constants, not settings: 4 page reads (`ReadingLimit`), 12 model calls (`call_limit`).
- Prompt: `backend/app/ingest/pool/identity.md`, the text agreed in conversation (rules: similar names are not
  the same; a shared parent is not the same; different CINs alone do not prove different; renames can be the same;
  SAME only with clear evidence; unsure when in doubt; avoid wrong merges over duplicates).
- Input to the model: the pool row (name, category, CIN, website from `signals`) and each candidate's
  `funders` row (id, name, aliases, website, cin, legal_form, parent_id, registered_address).
- Checked in code after the model answers: a SAME whose `funder_id` is not one of the candidates, or with no
  `source_urls`, becomes UNSURE.
- Traced as `sangam_pool_identity`, session `funder-pool-<id>-<attempt>`, so it sits beside the run in Langfuse.

**`backend/app/ingest/pool/job.py`**: `process(pool, row, research, decide=None)`. In the close-name branch,
when `decided == "pending"` and `decide` is set:

| Decision | `resolution_queue` | Row |
|---|---|---|
| SAME (cited) | upsert `accepted`, `resolved_funder_id`, `notes = "model: <reason> · <urls>"` | `skipped`, `funder_id` set (existing accepted path) |
| DIFFERENT | upsert `rejected`, `notes` | falls through to research (existing rejected path) |
| UNSURE | upsert `pending`, `notes = "model unsure: …"` | falls through to research |

`decide=None` keeps today's behaviour exactly: the row parks for a person.

**`backend/app/ingest/pool/worker.py`**: builds the check lazily on first use, as it does `Scout`, and passes
`decide` to `job.process`. `POOL_IDENTITY_MODEL=off` passes `None`.

**`backend/app/core/config.py`**: `pool_identity_model: str = ""`, blank meaning `research_model`, `off` disabling.

No migration. No catalog entry. No route. No frontend.

## 5. Security review

- **No new endpoint**, so no new auth surface. The worker already runs on the owner pool.
- **Web text can steer the model.** A page could say "this is the same as HDFC Bank". Two guards: a SAME must
  name a funder from the candidates list (it cannot invent a target), and it must cite a source URL.
  The worst a steered model can do is merge into one of the 1–3 candidates the matcher already proposed.
  Every SAME is listed after the batch and checked by a person (milestone 2).
- **Fetches** go through Scout's `read_page`, so `guarded_client` (`core/egress.py`) refuses private addresses.
- **No PII**: company names, CINs and websites only. No secrets read; keys come from the environment.

## 6. Testing

Unit tests, no database (`tests/test_funder_pool.py` style, fake `decide`):

- SAME with a cited candidate id → `accepted`, row `skipped`, `funder_id` set.
- SAME naming a funder not in the candidates → treated as UNSURE, research runs.
- SAME with no URL → UNSURE.
- DIFFERENT → `rejected`, research runs.
- `decide` raises or returns nothing → UNSURE, research runs, the row is not failed.
- `decide=None` → parks for a person, exactly as today.
- A person's earlier answer still wins: `accepted` or `rejected` in `resolution_queue` skips the model.

One eval, `tests/evals/test_pool_identity.py` (mark `eval`, costs about $0.50): the 13 real pairs above must
come back DIFFERENT or UNSURE, never SAME; one real rename, "Shriram Transport Finance Company" against
Shriram Finance (renamed in 2022), should come back SAME.

## 7. Milestones

#### Milestone 1: the check, behind a switch
- **Deliverable**: a close name in the pool is decided by the model; `POOL_IDENTITY_MODEL=off` restores today's behaviour.
- **Touches**: backend only.
- **Key tasks**: [ ] `identity.py` + `identity.md` [ ] `job.py` branch [ ] worker wiring [ ] setting [ ] `BUILDERS` entry [ ] unit tests [ ] eval
- **Acceptance criteria**: `cd backend && pytest tests/test_funder_pool.py tests/test_architecture.py` passes;
  `make evals K=pool_identity` shows 13 not-SAME and the rename SAME.

#### Milestone 2: the 45-funder batch (no code)
- **Deliverable**: a measured run with the check on.
- **Key tasks**:
  - [ ] Deploy; set `indian_csr` `daily_cap = 45`, then enable it.
  - [ ] Put the 13 parked rows back to `pending` with `priority_override = 0`, so they run first; their
        `resolution_queue` rows are still `pending`, so the model decides them.
  - [ ] After the batch, list every decision.
- **Acceptance criteria**: for every SAME, a person agrees; zero rows parked as "a close name"; cost per check from
  Langfuse (`sangam_pool_identity`). The query:
  ```sql
  SELECT raw_name, status, resolved_funder_id, notes FROM resolution_queue
   WHERE source = 'funder_pool' AND notes LIKE 'model%' ORDER BY id;
  ```

## 8. Open questions and risks

- **UNSURE still asks a person.** If most checks come back UNSURE, the queue barely shrinks. Milestone 2 tells us;
  the fix then is the prompt, not the flow.
- **A merge is the only irreversible step.** SAME skips research for that row. If a person later disagrees, they
  set the row back to `pending` and the `resolution_queue` row to `rejected`; the next attempt researches it.
- **Model tier.** Sonnet, because a wrong SAME is the costly mistake. Haiku is cheaper and could be tried by
  setting `POOL_IDENTITY_MODEL` once the 45-funder results are in.
- **Out of scope, on purpose:** the matcher's scoring (most of these candidates should never have been proposed)
  and the same check for Scout chats and Review. Both can follow if the batch shows the check works.
