# Long runs without the memory blow-up: slimmer AG-UI events, then no CopilotKit

Draft v1 · 2026-10-11 · branch `docs/drop-copilotkit`

## 1. Goal

**A 30-minute Import finishes on a laptop and on Vercel, because nothing between the backend and the
browser keeps a copy of the run.**

Success means:

- An 8-organisation Import runs to the end locally with the frontend container under 1 GB.
- The browser talks AG-UI (Agent–User Interaction protocol, the event stream the backend already
  speaks) straight to the backend's `/agent` and `/ingest`. `/api/copilotkit` is gone.
- `@copilotkit/react-core`, `@copilotkit/runtime` and the Python `copilotkit` package are gone.
- Ask and Scout look and behave exactly as today, pause cards included.

### What happened

> **The rule:** a run must not depend on a process that grows with the run's length.
> **Example:** Priya starts an 8-funder Import at 17:03. At 17:27 the Next.js dev server is killed
> for running out of memory (`OOMKilled: true`), the backend sees the browser go away, and the run
> ends `cancelled: client disconnected` (Langfuse trace `9b31e258…`) with three funders unsaved.
> **Why it matters:** the same route runs as a Vercel function with less memory than Docker had.

Two causes multiply:

| cause | where | evidence |
|---|---|---|
| The relay keeps every event of a running stream, three times | `frontend/app/api/copilotkit/[[...slug]]/route.ts` uses `InMemoryAgentRunner` | its v1.73.0 type docs: `currentRunEvents` plus two `ReplaySubject(Infinity)` buffers; `maxBytes` is enforced only when a run completes |
| Every event carries a copy of the LangGraph event it came from | `ag_ui_langgraph` sets `raw_event=event` on everything it emits | `emit_raw_events` defaults to `True`; nothing in `app/` turns it off, and no frontend file reads `rawEvent` |

### Why CopilotKit can go

It came with the first scaffold (`dce571d`, "Next.js+CopilotKit"). Sangam uses none of what it is
usually picked for:

| CopilotKit feature | used here? |
|---|---|
| ready-made chat UI, generative UI, frontend tools | no — Ask and Scout render their own chat |
| `useAgent`, `runAgent`, `stopAgent` | yes, in `lib/useAgentChat.ts` — a wrapper over `@ag-ui/client`'s `HttpAgent` |
| `useInterrupt` | yes, three cards — one custom event in, one `forwardedProps` out |
| `useAgentContext` | yes, once — AG-UI's own `context` field |
| the server relay | yes — and it is what ran out of memory |

## 2. Blast radius

There is no domain map in this repo. This table was built by hand from `CLAUDE.md`'s Architecture
section and a grep for `@copilotkit`, `@ag-ui`, `copilotkit` and `LangGraphAGUIAgent`. No table,
migration or SQL catalog entry is involved.

| surface | hop | why affected | status | notes |
|---|---|---|---|---|
| `backend/app/core/lifespan.py` | 1 | builds both AG-UI agents | in scope | `emit_raw_events=False` |
| `backend/app/integrations/tracing.py` (`SessionScopedAGUIAgent`) | 1 | the agent class; extends copilotkit's `LangGraphAGUIAgent` | in scope | base becomes `ag_ui_langgraph.LangGraphAgent` in M4 |
| `backend/pyproject.toml` | 1 | `copilotkit>=0.1.96` | in scope | removed in M4 |
| `frontend/app/api/copilotkit/[[...slug]]/route.ts` | 1 | the relay | in scope | deleted in M3 |
| `frontend/lib/AgentProviders.tsx` | 1 | `CopilotKitProvider`, token header | in scope | becomes our own provider |
| `frontend/lib/useAgentChat.ts` | 1 | `useAgent`, `useCopilotKit` | in scope | rewritten on `HttpAgent` |
| `frontend/features/ingest/components/SourcesCard.tsx`, `SaveQuestions.tsx`, `ImportApproval.tsx` | 1 | `useInterrupt` | in scope | swap to our `useInterrupt` |
| `frontend/features/ingest/lib/useRunPause.ts` | 1 | `useAgent`, `INTERRUPT_EVENT_NAME` | in scope | — |
| `frontend/features/ingest/ScoutChat.tsx` | 1 | `useAgentContext` for ticked sources | in scope | — |
| `frontend/features/ask/SignedInWorkspace.tsx`, `features/ingest/ImportPage.tsx` | 2 | mount `AgentProviders` | in scope | import path unchanged |
| `frontend/features/ask/WorkspaceLoader.tsx`, `features/ingest/ImportLoader.tsx` | 2 | lazy-load "the CopilotKit runtime" | in scope | comments only; lazy loading stays |
| `frontend/features/{ask,ingest}/lib/threads.ts` | 2 | import the `Message` type from `@ag-ui/client` | unaffected | that package stays |
| `backend/app/ingest/middleware.py` (`ticked_sources`) | 2 | reads `state["ag-ui"]["context"]` by description | unaffected | the new hook sends the same description |
| `backend/app/integrations/tracing.py` (`key_resume`) | 2 | addresses a legacy resume to one open pause | unaffected | the new hook sends the same `forwardedProps.command.resume` |
| `backend/app/main.py` CORS + `AuthMiddleware` | 2 | the browser now calls `/agent` and `/ingest` directly | in scope (verify) | origins already allow the frontend; `allow_headers=["*"]` |
| `docker-compose.yml` `frontend` service | 1 | no restart policy; `AGENT_URL` | in scope | M1; `AGENT_URL` stays for server components' REST base |
| `Makefile` `dev-frontend` | 2 | sets `AGENT_URL` | unaffected | still used by `lib/api/client.ts` |
| `frontend/package.json` | 1 | two CopilotKit packages; `@ag-ui/client` pinned at 0.0.59 | in scope | M3 removes; pin reviewed |
| `CLAUDE.md` | 2 | architecture diagram, "talks to the backend two ways", `AGENT_URL` asymmetry, 1800 s on the copilotkit route | in scope | updated with each milestone |
| `backend/tests/test_tracing.py` | 2 | patches `LangGraphAGUIAgent.prepare_stream`; checks `emit_subagent_events` survives `clone()` | in scope | M4 retargets |
| Langfuse tracing | 2 | `SessionScopedAGUIAgent.prepare_stream` and `run` flush | unaffected | same overrides on the new base |
| Design system ("Sangam Design System v2") | — | no component, token or screen changes | unaffected | hooks only; nothing renders differently |
| 1800 s limits: `maxDuration` in the copilotkit route, `functions` in `backend/vercel.json` | 2 | must match today | in scope (M3) | the route's goes with the route; the backend's stays |

## 3. High-level design (HLD)

```
today                                         after M3
browser ─AG-UI─▶ Next /api/copilotkit         browser ─AG-UI─▶ FastAPI /ingest
  (CopilotKit hooks)  │ InMemoryAgentRunner     (@ag-ui/client HttpAgent
                      │ buffers the run ×3       + our ~150-line hooks)
                      ▼
                 FastAPI /ingest
```

- **Postgres, Neo4j, Storage, the model:** untouched. History still loads from the checkpointer via
  `/api/threads/{id}/messages`.
- **Endpoints:** none new. `/agent` and `/ingest` gain a browser caller; `/api/copilotkit/*` goes.
- **Key trade-off.** We lose CopilotKit's in-memory replay: a reload mid-run cannot rejoin the live
  stream from the relay's buffer. On Vercel that only worked when the reload reached the same
  instance, so little is really lost — after a reload the screen shows the saved checkpoint, as a
  reopened chat does today. In exchange no process holds the run, and the frontend function stops
  needing 1800 s.

## 4. Low-level design (LLD)

### M1 — stopgap

- `docker-compose.yml`, `frontend:` gets `restart: unless-stopped`, so an out-of-memory kill comes
  back without a person noticing.
- `README.md` Prerequisites: Docker Desktop memory at 12 GB or more for long Imports, until M3.

### M2 — slimmer events, measured

- `scripts/agui_bytes.py`: posts one AG-UI run to `localhost:8010/ingest` with `Bearer dev`
  (`DEV_AUTH=1`, local only), reads the SSE stream, and prints bytes and count per event type, with
  `rawEvent` bytes split out. Run it on a fixed one-funder Import before and after.
- `backend/app/core/lifespan.py`: both `SessionScopedAGUIAgent(...)` calls pass `emit_raw_events=False`.
  Check that `clone()` carries it (it is in `ag_ui_langgraph`'s clone table, line 726).
- Decided by the measurement, not now: if `STATE_SNAPSHOT` or researchers' `TEXT_MESSAGE_CONTENT`
  are still a large share, `SessionScopedAGUIAgent._dispatch_event` drops them. The browser reads
  no `agent.state`, and `useAgentChat` already ignores a researcher's prose (`!m.subagentRunId`).

> **The rule:** only drop an event type the browser provably does not read.
> **Example:** `STATE_SNAPSHOT` is safe to drop if a grep for `.state` in `lib/` and `features/` stays
> empty; `SUBAGENT_STARTED` is not, because `useAgentChat` builds `laneOwners` from it.
> **Why it matters:** a dropped event fails silently — the board just stops moving.

### M3 — the browser talks AG-UI directly

New files under `frontend/lib/agui/`:

| file | what it does |
|---|---|
| `AgentProvider.tsx` | replaces `CopilotKitProvider`: holds the Supabase token (the logic now in `AgentProviders.tsx`) and a `Map<agentId, HttpAgent>` so the chat, the three cards and `useRunPause` share one agent per thread, as CopilotKit's registry did |
| `useAgent.ts` | `useAgent(agentId, { url, threadId })`: gets or creates the `HttpAgent` with `url = NEXT_PUBLIC_API_URL + "/agent"` or `"/ingest"`, re-renders on `onMessagesChanged` and run start/finish (throttled to 80 ms, today's `throttleMs`), and exposes `run({ forwardedProps, context })` and `stop()` (`abortRun()`) |
| `useInterrupt.ts` | the legacy flow CopilotKit implements: on `CUSTOM` `on_interrupt` remember `value`; on run finalized set `pending`; `resolve(payload)` runs with `forwardedProps: { command: { resume: payload, interruptEvent: value } }`; cleared on run start and failure |

Edits:

- `lib/useAgentChat.ts` keeps its return shape (`turns`, `send`, `stop`, `isRunning`, `isReady`,
  `isLoadingHistory`, `laneOwners`), so `ScoutChat` and the Ask workspace do not change.
- `ScoutChat.tsx`: `useAgentContext(...)` becomes a `context` entry passed to `send`, with the
  description `"Sources the person ticked for this Import run"` — the exact string
  `TICKED_SOURCES` in `app/ingest/middleware.py` matches on.
- `SourcesCard.tsx`, `SaveQuestions.tsx`, `ImportApproval.tsx`, `useRunPause.ts`: import from
  `@/lib/agui` instead of `@copilotkit/react-core/v2`. `INTERRUPT_EVENT_NAME` becomes our constant.
- Delete `app/api/copilotkit/[[...slug]]/route.ts` and the two CopilotKit packages. Keep
  `@ag-ui/client`; revisit its 0.0.59 pin (`bbc2274`) once CopilotKit no longer constrains it.
- `CLAUDE.md`: the architecture diagram, "The frontend talks to the backend two ways", the
  `AGENT_URL`/`NEXT_PUBLIC_API_URL` asymmetry, and the 1800 s paragraph (backend only).

### M4 — the Python package

- `tracing.py`: `SessionScopedAGUIAgent` extends `ag_ui_langgraph.LangGraphAgent`. The base takes
  `emit_subagent_events` itself, so the "copilotkit's `__init__` drops this flag" workaround goes.
  None of copilotkit's additions are used: its `copilotkit_manually_emit_*` events and
  `copilotkit:emit-messages` metadata appear nowhere in `app/`.
- `pyproject.toml`: drop `copilotkit`; its description stops saying "for CopilotKit".
- `tests/test_tracing.py`: patch target becomes `LangGraphAgent.prepare_stream`.

## 5. Security review

- **Auth.** `/agent` and `/ingest` already require `Depends(chat_access)` and sit behind
  `AuthMiddleware`. The relay only forwarded the browser's `Authorization` header, so the check is the
  same one. `HttpAgent` sends `Authorization: Bearer <token>` from the provider.
- **CORS.** The browser already calls the REST API cross-origin, so `ALLOWED_ORIGINS` (and
  `allowed_origin_regex` on Vercel) already admit the frontend. Verify a preflight for `POST /ingest`
  with `Accept: text/event-stream` on staging before M3 ships.
- **Less leaves the server.** Today every event carries its raw LangGraph event to the browser,
  including run metadata such as `langfuse_user_id` and model settings. `emit_raw_events=False`
  stops that.
- **Validation.** Unchanged: `RunAgentInput` is Pydantic, parsed by `ag_ui_langgraph`.
- **Token lifetime.** A run's token is checked once, at the request. A 30-minute run outliving a
  1-hour token is no different from today.
- **No catalog, PII or secret change.** `DEV_AUTH=1` for the M2 script stays local only.

## 6. Testing

The team rule is no new tests in PRs; existing ones a change breaks get fixed. So:

- M2: `pytest -m "not integration"` stays green. The byte table before and after goes in the PR.
- M3: `npm run lint` and `npm run build`. Then a manual pass, in this order: Ask question with
  citations; Ask stop mid-answer; Scout with sources ticked (no card); Scout with nothing ticked
  (sources card); a save that pauses for approval (`ImportApproval`); two parallel writers pausing
  together (`SaveQuestions`, addressed by slug through `key_resume`); a message sent mid-run (queued);
  reload a finished Import (history loads).
- M4: `tests/test_tracing.py` retargeted; full unit suite green.

Edge case: an interrupt with no pending card after a reload. Today `useRunPause` reports it as
"stuck"; the new `useInterrupt` must do the same, not render nothing.

## 7. Milestones

#### Milestone 1: an out-of-memory kill comes back on its own
- **Deliverable**: the frontend container restarts after a kill; the README says how much memory long Imports need
- **Touches**: docker-compose, README
- **Key tasks**: [ ] `restart: unless-stopped` on `frontend` [ ] README Prerequisites line
- **Acceptance criteria**: `docker kill -s KILL sangam-frontend-1 && sleep 10 && docker ps --filter name=frontend` shows it up

#### Milestone 2: events carry only what the browser reads, measured
- **Deliverable**: a byte table per event type, before and after; `raw_event` off on both agents; any further drop justified by that table
- **Touches**: backend, scripts
- **Key tasks**: [ ] `scripts/agui_bytes.py` [ ] measure a one-funder Import [ ] `emit_raw_events=False` in `lifespan.py` [ ] measure again [ ] decide on `STATE_SNAPSHOT` and researcher prose from the numbers [ ] CLAUDE.md note
- **Acceptance criteria**: `DEV_AUTH=1 python scripts/agui_bytes.py --funder "Wipro Foundation"` shows `rawEvent` at 0 bytes; `docker stats` peak for the frontend during an 8-funder Import recorded in the PR

#### Milestone 3: no relay — the browser speaks AG-UI to the backend
- **Deliverable**: Ask and Scout run on `@ag-ui/client` with our hooks; `/api/copilotkit` and both CopilotKit npm packages gone
- **Touches**: frontend, CLAUDE.md
- **Key tasks**: [ ] `lib/agui/AgentProvider.tsx`, `useAgent.ts`, `useInterrupt.ts` [ ] `useAgentChat.ts` on the new hook, same return shape [ ] three cards and `useRunPause` switched [ ] ticked sources as `context` [ ] delete the route and packages [ ] CORS preflight checked on staging [ ] CLAUDE.md
- **Acceptance criteria**: `grep -r "@copilotkit" frontend --include=*.ts* -l` is empty; `npm run build` passes; the eight-step manual pass above; an 8-funder Import finishes with the frontend under 1 GB

#### Milestone 4: no CopilotKit in the backend either
- **Deliverable**: `SessionScopedAGUIAgent` on `ag_ui_langgraph.LangGraphAgent`; `copilotkit` out of `pyproject.toml`
- **Touches**: backend, tests
- **Key tasks**: [ ] swap the base class [ ] drop the flag workaround [ ] retarget `test_tracing.py` [ ] remove the dependency
- **Acceptance criteria**: `grep -rn copilotkit backend/app backend/pyproject.toml` is empty; `pytest -m "not integration"` green; one Ask and one Scout turn traced in Langfuse with input and output

M2 and M4 are backend-only and can ship in either order. M3 needs no backend change, but M2 first
means the measurement covers the stream M3 will carry.

## 8. Open questions and risks

- **Researcher prose live.** Dropping researchers' `TEXT_MESSAGE_*` saves bandwidth, but their text
  still arrives in the final `MESSAGES_SNAPSHOT`. Is any screen meant to show it while it streams?
  Today nothing does. Decide with M2's numbers.
- **Reload mid-run.** After M3 a reload shows the checkpoint, not the live stream, until the run
  ends. Acceptable? If not, the follow-up is rejoining via LangGraph's own stream, not a relay.
- **Vercel memory, unverified.** We believe a long deployed Import dies the same way but have not
  seen one fail. Check the `sangam` project's function logs for an out-of-memory on
  `/api/copilotkit` before M3, to know whether this is a production fix or only a local one.
- **`@ag-ui/client` version.** It is pinned at 0.0.59 for CopilotKit's types. Moving it may change
  `subagentRunId` on messages or the `onSubagentStartedEvent` callback the lanes depend on.
- **Parallel pauses.** CopilotKit's standard (non-legacy) flow can address several interrupts at
  once. The backend runs the legacy flow and `key_resume` addresses by slug; M3 keeps the legacy
  flow only. If the backend ever turns on `emit_interrupt_outcome`, the hook must grow.
