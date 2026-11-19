# Ask: an answer audit that can be trusted (#451, #452)

Status: Draft v1, 2026-11-20. Part of epic #450.

## Why

After every Ask answer, a cheap second model (`SQL_AUDIT_MODEL`, Haiku 5.5) checks the answer against
the query results and sends Langfuse an `answer_audit` score: 1 = ok, 0 = flagged. Nobody in the chat sees
it (#322). It is the only automatic signal of a wrong answer, and today it cannot be used:

- **#451, wrong flags.** `collect_turn` gives the audit only the current question's results. An answer that
  reuses a fact an earlier question found is called unsupported. 19 Nov, one chat: "what does axis bank
  foundation do?" (21:51) found `[activity:1]`; "who works in udalguri?", "where does kabil work?" and "top
  5 funders in livelihoods" reused it and were all flagged "not in any tool result". 18 of 21 scores are
  flags; about 13 are wrong.
- **#452, no verdict.** `MAX_TOKENS = 1024` covers thinking and the verdict. 4 of 25 audits spent it all
  thinking and wrote nothing (22:03, "Which organisations in the base work in Assam?": 1,024 reasoning
  tokens, 0 output), so those answers have no score.

Success: the audit's flags agree with a person's labels on ≥ 80% of answers, and every answer it audits
gets a verdict.

Non-goals: showing the audit in the answer; moving the judge into Langfuse; Langfuse Prompt Management
for the audit prompt; changing the four checks.

## Approaches

| | Trade-off | |
|---|---|---|
| Langfuse-managed LLM-as-a-judge evaluator | Langfuse runs it, with sampling; but an evaluator sees one observation only ("do not load sibling or child observations"), so every trace would carry ~30k chars of results on its root, and our Anthropic key would sit in Langfuse | Rejected |
| **Our code judges, Langfuse stores the score** ("Scores via API/SDK"), plus Langfuse's annotation queue and Score Analytics to check it | Only the app holds the results, which is the case the docs give for SDK scores | **Chosen** |

Langfuse's multi-turn method ("N+1" over a dataset) is for offline testing, not live scoring.

## Design

```
Ask turn ──► after_agent: answer_audit (app/ask/middleware.py)
                 │
                 ▼
        audit_turn (app/ask/audit.py)
          ★ collect_chat: every turn's results, each tagged with its question; newest kept to EVIDENCE_CHARS
          ★ structured output {verdict, check, reason}; MAX_TOKENS 4096
                 │
                 ▼
        score_answer ──► Langfuse  answer_audit (0/1, comment = reason)  ★ metadata.check
                                     │
         ★ annotation queue "Ask answer review" ──► answer_correct (person's label)
         ★ scripts: re-audit past turns ─────────► answer_audit_v2
                                     │
                         Score Analytics: answer_correct vs answer_audit / _v2
```
★ = new

- **Whole-chat evidence (#451).** `collect_turn` keeps this turn's question and answer but collects results
  from every turn. A result from an earlier turn is headed `(earlier question: "<first 120 chars>")`. The
  `_newest` cap stays at `EVIDENCE_CHARS`, so the most recent results win and the cost stays near today's
  (~8k tokens on Haiku, about 0.1¢). `has_data` and `refused` still describe this turn only: a turn that ran
  no query and only talks is not audited. The prompt says a fact is supported by any result above,
  including an earlier question's.
- **A verdict every time (#452).** `model.with_structured_output(Verdict, method="json_schema",
  include_raw=True)`: `verdict` ("ok" | "warn"), `check` ("grain" | "filters" | "false_zero" | "numbers" |
  "unsupported" | null), `reason` (one sentence). `MAX_TOKENS = 4096`. A `max_tokens` stop or a parse
  failure still returns None and logs, as now. The regex JSON parse goes.
- **`check` on the score.** `score_answer` gains `metadata={"check": ...}` so flags can be split by kind.
  The score stays numeric 0/1 under the same name, so dashboards keep their history.

## Checking it (Langfuse's recommended way)

- A score config `answer_correct` (boolean) and an annotation queue "Ask answer review", created once by a
  script (`backend/scripts/langfuse_audit_review.py setup`). Creating them changes the Langfuse project, so
  it runs only when the user says so.
- The same script's `rerun` rebuilds each past turn from the local checkpoints (the messages up to that
  turn's answer), runs the new `audit_turn`, and sends `answer_audit_v2` to that turn's trace (matched by
  session id and question text). No model call for Ask itself; one Haiku call per turn.
- The person labels ~30 answers in the queue. Score Analytics compares `answer_correct` with
  `answer_audit` and `answer_audit_v2` (Cohen's kappa, confusion matrix). Bar: v2 agrees on ≥ 80%.

## Milestones (stacked PRs)

| | PR | Exit gate |
|---|---|---|
| M1 | This plan, plus whole-chat evidence, structured verdict, `check` metadata, tests | `pytest tests/test_audit.py tests/test_cov_agent_middleware.py` pass; a re-asked follow-up that reuses an earlier fact scores 1 locally |
| M2 | `scripts/langfuse_audit_review.py` (`setup`, `rerun`), tests for the turn rebuild and trace matching | User approves and runs `setup`; `rerun` sends `answer_audit_v2` for the 19 Nov chats; user labels; Score Analytics shows v2 ≥ 80% |

## Security

No new route, table or permission. The audit reads only what the turn's tools already returned to the
caller. The script runs on a developer's machine with the backend's Langfuse keys, reads the local
checkpoints, and writes scores only. It never prints keys.

## Left to the builder

The exact wording of the earlier-question heading and of the prompt change; how many turns back the
re-run goes.
