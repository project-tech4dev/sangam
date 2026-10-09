# Import on LangChain middleware

## Context
This builds on `2026-10-09-model-tiers.md`. With the tiers in place, Import still had three gaps:
- **One overloaded model failed a whole researcher.** The Anthropic SDK retries twice, then the run aborts.
- **A researcher had no hard budget.** Only `recursion_limit` stopped it, and up to eight run in parallel on long PDFs.
- **A malformed save lost the research.** `save_research`'s schema is large, and when the research tier sends an invalid payload, the findings are gone.

All of it is in `backend/app/ingest/middleware.py` and is wired in `build_ingest_agent`.

## What each agent runs

| Agent | Added middleware |
|---|---|
| Supervisor (`MODEL`) | fallback → `RESEARCH_MODEL`; summaries written by `UTILITY_MODEL` |
| `entity-researcher` (`RESEARCH_MODEL`) | `ReadingLimit`; model-call limit; escalation to `MODEL` after a failed save; fallback → `MODEL`; `ResearchRubric` graded by `UTILITY_MODEL`; eviction at 8k tokens; summaries by `UTILITY_MODEL` |
| `catalog-writer` (`UTILITY_MODEL`) | model-call limit (12); fallback → `RESEARCH_MODEL` |
| `workbook-reader` (`UTILITY_MODEL`) | fallback → `RESEARCH_MODEL` |

- **Fallbacks:** each tier falls back to the next model that differs from its own. With every tier set to `MODEL`, there are none.
- **Reading limit:** `RESEARCH_PAGE_LIMIT` (default 20) counts `read_page`, `fetch_document` and `read_document_pages` together.
  - It is our own small `wrap_tool_call`, because `ToolCallLimitMiddleware` limits one tool name at a time.
  - Past the limit, a read returns a refusal message. The researcher then saves with `status: partial` and "Stopped at the reading limit" in `stopped_reason`.
  - The Working board shows that row as "Stopped at the reading limit".
  - The prompt's soft budget is about eight searches and six documents, so 20 is a backstop.
- **Model-call limit:** `RESEARCH_MODEL_CALL_LIMIT` (default 60) ends a looping run. An ended run has no structured summary, so the task tool reports its last text.
  - Both defaults are conservative guesses. Tune them from Langfuse once runs on these tiers exist.
- **Escalation:** after `save_research` returns an argument error (`status="error"`), the rest of the researcher's run uses `MODEL`.
  - A `REFUSED` result, or a database failure (`save_research failed:`), doesn't escalate, because a stronger model would get the same answer.
  - The trigger is read from the run's messages, so there's no extra state.
  - The escalation is left out when the research tier already is `MODEL`.
- **Rubric:** `ResearchRubric` is deepagents' `RubricMiddleware` with the fixed rubric `prompts/research_rubric.md`.
  - It checks that the save succeeded, gaps have reasons, a partial run says why, and the summary's counts match the save.
  - It deliberately doesn't ask for more research.
  - The rubric is passed to the hooks, not written to state, because a public `rubric` key would flow back to the supervisor.
  - The grader sees each `save_research` call as a digest, since the full payload would be cut at 4,000 characters.
  - At most one revision.
- **Eviction:** results over 8k tokens go to a file that the researcher pages back with `read_file`. Other agents keep the 20k default.
- **Summaries:** the same-name `SummarizationMiddleware` replaces deepagents' own on the supervisor and the researcher.
  - The trigger and keep thresholds are computed from the agent's own model, so they don't change: Opus 5.5 and Sonnet 5.5 have no profile, so 170k tokens and 6 messages.
  - Input to the summarizer is capped at 150k tokens to fit Haiku's window.
- **Tracing:** the Import trace carries the research and utility model specs as tags, beside the main model.

## Cost to watch
A rubric revision is one Haiku grade plus one more research-tier turn. Eight parallel researchers can add up to eight of each per import. The `research rubric:` log line counts how often revision happens.

## Not used, and why
- **`ModelRetryMiddleware` / `ToolRetryMiddleware`:** the SDK already retries, and our tools return error strings instead of raising.
- **`LLMToolSelectorMiddleware`:** two to nine tools per agent is too few to be worth it.
- **Model-written memory, `AsyncSubAgent`:** a web page could plant instructions that persist, and there is no Agent Protocol server on Vercel.

## To verify live
With one funder and `RESEARCH_PAGE_LIMIT=3`, check that:
- the researcher saves;
- the row reads "Stopped at the reading limit";
- Langfuse shows the grader on Haiku;
- after a rubric revision, the task result is still a `ResearchSummary`.
