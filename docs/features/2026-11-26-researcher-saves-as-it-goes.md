# Scout researcher: save as it goes, check in code, judge quality as a score

Fixes #479 and #475, and the grader half of #325. Stacked on #470 (`feat/partial-update-gap-search`), whose save
path it builds on. One PR.

## 1. Why

Trace `c2b6973d` (HCL, incremental, 26 Nov): the research took ~1 min and $0.33; saving took ~11 min and $2.33.
The 57-fact payload was written four times:

| Step | What happened | Cost |
|---|---|---|
| 9→10 | Sonnet sent `findings` as a string ending `,"replace":false}`; refused as a format error | $0.34 |
| 11→12 | Moved to Opus, rewrote everything; refused: `identity.populations` and `.lenses` have no finding or gap | $1.10 |
| 13→14 | Opus rewrote everything; refused: 66 findings already saved today, 57 offered | $0.62 |
| 17→19 | The Haiku grader said `needs_revision` on three rules the save met; Sonnet rewrote with `replace=true` | $0.27 |

The morning's full run (`1b117e6e`) lost $1.32 the same way to one empty extra key, `goals_note: ""`.

## 2. Design

```
entity-researcher (Sonnet)
  read_page / search / documents ...
  record_findings(findings, gaps, unplaced)   NEW: a few at a time, each item checked alone
        │ accepted items ──► Draft (per researcher, ContextVar beside snapshots.COLLECTED; not in messages,
        │                    so a summary or cleared tool results cannot lose it)
        └ refused items ──► one line each; only those are sent again
  save_research(entity_name, entity_kind, status, summary, ...)   CHANGED: no findings argument
        ├ EntityResearch built from the Draft; contract.unanswered names only what is missing
        ├ MERGED into today's row (brief.merge_findings), snapshot_ids unioned: no shrink refusal, no `replace`
        └ ResearchJudge (after the researcher ends)   NEW: Haiku scores quality to Langfuse, never retries
  REMOVED: ResearchRubric (Haiku gate), digest_saves, research_rubric.md
  CHANGED: EscalateAfterFailedSave counts content refusals in the Draft (2 → MODEL); format errors never escalate
ChosenSources (supervisor)   CHANGED: opens the Draft per task, and writes fact_count, concepts_found, saved and
                             entity_kind into the ResearchSummary from what was saved
```

| Change | Where |
|---|---|
| Draft, per-item validation, string and unknown-key clean-up, dedupe | `research/draft.py` (new) |
| `record_findings`; slim `save_research` with merge | `tools/research_tools.py` |
| Rubric removed, escalation on the Draft, summary counts from code, `ResearchJudge` | `middleware.py`, `agent.py` |
| `RESEARCH_JUDGE_MODEL` (default `UTILITY_MODEL`, `off` disables) | `core/config.py`, `.env.example` |
| Prompt, both pull skills, tool table, tool label, board's entity name | `prompts/entity_researcher.md`, `skills/research/*`, `instructions.md`, `frontend/features/ingest/lib/` |

**Code checks replace the grader's six rules.** Save worked: the tool's own result. Gap reasons: the `Gap` type, which
allows `not_reached`, as the prompt does. Partial has a reason: `EntityResearch`. Untagged programmes:
`contract.unanswered`. Counts and kind in the summary: written by code, not checked.

**Quality is a score, not a gate.** `ResearchJudge` sees the saved findings with their quotes (not the pages) and
scores correctness (the quote supports the value), consistency (no two findings conflict), relevance, source quality,
and completeness against the goals. It writes `research_*` Langfuse scores and never sends the researcher back.

**Warnings, not refusals:** a cited public URL no tool read this run is named in the save's reply.

**Trade-off:** the Draft lives in memory for the run. A crash loses what was recorded, as it loses everything today.

## 3. Expected effect, c2b6973d

| | Today | After |
|---|---|---|
| Full-payload writes | 4 | 0 (facts go once, in batches) |
| Opus calls in the researcher | 2 ($1.72) | 0 |
| Grader revisions | 1 ($0.27, 2 min) | 0 |
| Researcher cost / time | ~$2.66 / ~12 min | ~$0.7 / ~4 min (estimate) |
| Save schema in every call | ~17k tokens | under 1k (`record_findings` takes plain objects; keys come from `research_goals`) |

Works the same on DeepSeek (`compat:`): everything new is code or prompt, nothing needs strict tool use.

## 4. Exit gate

- Unit tests: fixtures shaped like the two failures (Langfuse cut the real inputs at ~4,000 characters), per-item
  refusal, merge of 66 + 57 keeping both, a superseded fact staying removed, unions of `snapshot_ids`, escalation
  only after two content refusals, summary counts from code, the judge's scores.
- `/code-review`, `/security-review`; no design-system change (no component or style touched).
- One HCL Import on the local database, compared with `1b117e6e` and `c2b6973d` on cost, time, facts and quotes.
  The supervisor's brief still calls HCL's RFPs "all closed", so a missing Global Grant is not this PR's regression.
