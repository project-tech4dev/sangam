# Scout: incremental discovery, research only what changed or is missing

Stacked on #496 (`feat/researcher-saves-as-it-goes`). One PR, three commits, one per milestone.

## 1. Why

HCL's incremental run `7925d873` (26 Nov) cost $1.66 and 15 min against $1.52 for the full run before it: incremental
planning and storage, not incremental discovery. It re-read 5 of the morning's pages (GreenEye, csrtimes,
thisweekindia, Deccan Chronicle, a Tavily page), waited 8 min on NSE PDFs that timed out in both runs (9 of 9), and was
given all 28 concepts as goals although the saved row answered 27.

`source_snapshots` already knows a re-read page was unchanged (rows 21, 22, 25, 29, 31 had `last_seen_at` bumped
with the same hash), and the saved row knows its open gaps. Nothing told the researcher.

## 2. Design

```
supervisor (Opus) ── "research HCL again"
   ├─ M3 NEW  check_changes(slug): the change check at free depth (fetch, hash, diff, evidence; no model), recorded
   │            as a source_check_runs row, plus the saved research's open gaps
   │            nothing a new run can fill → report it is current; no researcher
   │            fields unanswered, gaps not_reached → one top-up researcher (not_stated/blocked were tried)
   │            pages changed             → named in the report, with /import/check/<slug> for the update
   │            redesign / no baseline    → a full research, as today
   ▼
entity-researcher (Sonnet)
   ├─ M2 CHANGED research_goals: leads with the open gaps of the newest saved research row
   ├─ M2 CHANGED save_research: earlier days' findings answer the contract; their open gaps carry forward
   ├─ M1 CHANGED read_page: a version this entity's saved research read answers "already read on <date>"
   │            (fetched and hashed, not sent back); a second read_page in the run returns the text
   ├─ M1 CHANGED fetch_document: says when the file is a version saved research already read
   └─ M1 NEW  a host that timed out twice is skipped for an hour; a stalled document times out after 30 s
```

| Milestone | Change | Where |
|---|---|---|
| M1 | Already-read versions; slow hosts skipped; 30 s stall timeout for documents | `reading/snapshots.py`, `reading/fetch.py`, `prompts/entity_researcher.md` |
| M2 | Goals lead with open gaps; contract counts earlier days; gaps carry forward | `tools/catalog_tools.py`, `tools/research_tools.py`, `research/contract.py`, prompt |
| M3 | `check_changes` supervisor tool over `refresh/service.run(depth=free)` | `tools/catalog_tools.py`, `agent.py`, `instructions.md`, `frontend/features/ingest/lib/toolLabels.ts` |

**No migration.** Snapshots, research rows and check runs hold everything. Slow hosts live in process memory: a
restart forgets them, which costs one more 30 s wait.

**What is not incremental:** a fact we hold that is wrong but not a gap is not re-checked by the researcher; that is
the change check's job. A new page we never read is found only if it fills a gap (or by the full change check's
discovery).

**Scale note:** the already-read lookup joins `entity_research.snapshot_ids` without an index; at 10k funders add a
GIN index on it.

## 3. Expected effect, HCL a week later (estimates)

| Case | Today | After |
|---|---|---|
| Nothing changed | $1.66, 15 min | $0, under 1 min (M3) |
| 2–3 gaps open | $1.66, 15 min | ~$0.50, ~4 min (M1 + M2) |
| Redesign | $1.66 | ~$1.50, a full pull |

M1 alone: ~$1.10, ~7 min. A paid HCL re-run on the local database confirms these before merge.

## 4. Tests

M1: an unchanged version this entity's saved research read is not sent back, a second read is; a changed page is, and so is one read only for another entity; a host that
timed out twice is refused without a request, and forgotten after an hour. M2: goals list the newest row's open gaps; a
new-day save answering only gaps passes the contract and carries the other gaps. M3: each decision's reply, with and without something a new run can fill; no baseline;
a check already running; NGO scope.
