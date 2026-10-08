# Ask: reopen a past chat with its messages, from any browser

Status: Draft v1 · 2026-10-08 · fixes #123 · Ask Sangam only (Import chats unchanged)

## 1. Goal

**When Priya clicks a chat under Recent Chats, she sees every question, answer and trace she had, on any browser she signs in from.**

Success means:
- Reloading `/ask` and reopening a chat shows its turns, with the trace card and the "What this answer read" rail.
- Priya can ask a follow-up in that chat, and the agent answers with the earlier turns in context.
- Recent Chats is the same list on her laptop and her phone.

Today all three fail. Titles live in localStorage (`features/ask/lib/threads.ts`). Messages live only in the browser's agent object, so a reload empties them. The backend already saves every turn through the LangGraph checkpointer, but nothing reads it back.

## 2. Blast radius

Built by hand from `CLAUDE.md`, `catalog.py` (`threads` is in `KNOWN_EXCLUDED`) and `db/migrations/` (`0005`, `0024`, `0025`, `0027` shape `threads`). There is no domain map.

| surface | hop | why affected | status | notes |
|---|---|---|---|---|
| `threads` table | 0 | gets `title` and `updated_at` at claim time | in scope | columns exist since `0005`; no migration |
| `checkpoints` / `checkpoint_*` | 0 | read back through the compiled graph | in scope | read only; the owner connection reads them, and callers never do |
| `repositories/threads.py` `claim_thread` | 1 | writes the title and bumps `updated_at` | in scope | — |
| `core/security.py` `_own_thread` | 1 | passes the first question to the claim | in scope | — |
| `core/lifespan.py` | 1 | keeps the Ask graph on `app.state` for the read route | in scope | — |
| new `routes/threads.py` + `schemas/threads.py` | 2 | list chats and read one chat | in scope | `api/router.py` gains one line and one tag |
| `lib/useAgentChat.ts` | 2 | optional history loader, used by Ask only | in scope | Import passes none, so it is unchanged |
| `features/ask/AskWorkspace.tsx`, `ChatPane.tsx`, `lib/threads.ts` | 2 | list from the server, hydrate on open | in scope | — |
| `Sidebar.tsx`, `ChatsView.tsx` | 2 | same `ThreadMeta` shape, new source | in scope, no visual change | no design-system update needed |
| Sangam Import chats | 2 | share `useAgentChat` and `threads` | deferred | confirmed with the user, 2026-10-08; the Ask list leaves them out by their `import-` id prefix |
| SQL catalog / both agents' prompts | — | `threads` and checkpoints stay invisible to model SQL | unaffected | deliberate: chat history must never be `db_query`-able |
| Neo4j, Storage | — | not touched | unaffected | — |

## 3. High-level design (HLD)

```
open a past chat
  Sidebar ─ pick(id) ─▶ ChatPane(resume) ─▶ useAgentChat(loadHistory)
                                              │ isReady && no messages
                                              ▼
                     GET /api/threads/{id}/messages ──▶ app.can_open_thread(id, user)  (owner pool)
                                              │             └─ false → 404
                                              ▼
                     ask_graph.aget_state(thread_id) → langchain_messages_to_agui → JSON
                                              │
                                     agent.setMessages(...)  → turns, trace, rail render

list chats
  AskWorkspace ─▶ GET /api/threads ─▶ SELECT … FROM threads WHERE user_id = me AND id NOT LIKE 'import-%'  (caller pool, RLS)

save a chat (already happens; now also titled)
  POST /agent ─▶ chat_access → claim_thread(id, user, title) ─▶ checkpointer writes turns
```

New endpoints:
- `GET /api/threads`: the caller's Ask chats, newest first, at most 50.
- `GET /api/threads/{thread_id}/messages`: one chat's messages, in AG-UI shape.

Touched: Postgres (`threads`, the checkpoint tables). Not touched: Neo4j, Storage, the model.

**Key trade-off: read through the compiled graph, not the checkpointer.**
> **The rule:** history comes from `graph.aget_state(...)`, never `AsyncPostgresSaver.aget_tuple(...)`.
> **Example:** for local thread `64e91a44…`, `aget_tuple` returned `channel_values` with no `messages` key at all, while `aget_state` returned all 10 messages (user, 4 tool calls with results, final answer). LangGraph 1.2 does not store `messages` as one blob per checkpoint; the graph rebuilds it from writes.
> **Why it matters:** reading the raw saver returns an empty chat, which is the bug we are fixing.

**The title is written by the backend, at claim time.** `_own_thread` already parses `RunAgentInput`. It takes the first user message as the title. A frontend `PATCH` would need a new `GRANT UPDATE` and an RLS policy for no gain.

## 4. Low-level design (LLD)

### No migration

`0005_documents_threads.sql` already added `title`, `updated_by` and `updated_at`, with `threads_rail_idx (user_id, use_case, updated_at DESC)`.

> **The rule:** the Ask list leaves out Import chats by id, `thread_id NOT LIKE 'import-%'`.
> **Example:** Import claims its chats as `use_case='ask'` too (the column's check has no `'import'`), so `import-895253e4…` would otherwise show under Recent Chats. Its id is always `import-<uuid>` (`features/ingest/ImportWorkspace.tsx:23`).
> **Why it matters:** widening the check would mean a migration that has to reach staging before the backend, or every Import chat fails.

There is no title backfill: the title is not recoverable in SQL. The frontend falls back to the localStorage title, then to "Untitled chat".

### Backend

- `repositories/threads.py`
  - `claim_thread(pool, *, thread_id, user_id, title)`: on insert, write `title`. On conflict, for the owner only: bump `updated_at`/`updated_by` and fill `title` if it is still null. The `UNION ALL` fallback still returns the owner when the update is skipped (for example, staff opening someone else's chat).
  - `list_threads(pool, *, user_id, limit)`: `thread_id, title, created_at, updated_at` for `use_case = 'ask'` minus `import-` ids, ordered `updated_at DESC`. Uses `threads_rail_idx`.
  - `can_open(pool, *, thread_id, user_id) -> bool`: `SELECT app.can_open_thread(%s, %s)`.
- `core/security.py`: `_own_thread` passes a title to the claim. The title is the first `role == "user"` message, flattened to text, with whitespace collapsed and capped at 120 characters.
- `core/lifespan.py`: build the Ask graph once, keep it as `app.state.ask_graph`, and hand the same object to `add_langgraph_fastapi_endpoint`.
- `schemas/threads.py`: `ThreadOut {thread_id, title, created_at, updated_at}`, `ThreadMessagesOut {thread_id, messages: list[dict]}`.
- `api/routes/threads.py`
  - `GET /threads`: `require_user`, `PoolDep` (the caller pool; the `threads_read` policy applies).
  - `GET /threads/{thread_id}/messages`: `require_user`, `OwnerPoolDep` for `can_open`, 404 when false. Reads `request.app.state.ask_graph.aget_state(...)` and returns `model_dump(by_alias=True, exclude_none=True)`, so the frontend gets `toolCalls` and `toolCallId`. If the graph is not on `app.state` (a route-only app), it answers 503.
- `api/router.py`: import `threads`, add one tag and one `include_router`.

### Frontend

- `lib/useAgentChat.ts`: an optional `loadHistory?: () => Promise<Message[]>`. When it is set, `isReady` and the agent has no messages, call it once and `agent.setMessages(...)`. Return `isLoadingHistory`, which the composer treats as not ready, so a fast typist cannot have their message replaced by the arriving history.
- `features/ask/lib/useSangamChat.ts`: `useSangamChat(threadId, resume)` passes `loadHistory` only when `resume` is true. A brand-new chat never fetches.
- `features/ask/lib/threads.ts`: `fetchThreads()` and `fetchThreadMessages(id)` over `NEXT_PUBLIC_API_URL` with `authHeaders()`, the pattern `VaultView.tsx` uses. Keep `saveThread`/`loadThreads` only as the title fallback, and `titleFrom`.
- `features/ask/AskWorkspace.tsx`: list from `fetchThreads()`. Each null title falls back to the local one, then to "Untitled chat". Track `resume` for picked threads and pass it to `ChatPane`. Refresh the list after the first send completes.
- `features/ask/components/ChatPane.tsx`: take `resume`. Show "Loading this chat…" in the existing `composer-hint` while history loads. No new classes or tokens.

## 5. Security review

| check | answer |
|---|---|
| Auth on new endpoints | Both take `require_user`, so anonymous gets 401. Signed-out `/ask` is the preview and never calls them. |
| Whose chat | Messages: `app.can_open_thread` (owner, staff, or a team-visible thread), otherwise 404, not 403, so an id's existence does not leak. List: filtered to `user_id = me` on top of RLS, so staff see their own list, not everyone's. |
| Owner pool | The messages route reads checkpoints, which `0025` closes to `anon`/`authenticated`. It runs as owner, and only after `can_open_thread` passes. This is the one deliberate exception to "routers take `PoolDep`". |
| Claiming | The read path never calls `claim_thread`, which inserts: a GET must not claim an unowned thread. |
| Validation | `thread_id` is a path string bound as a parameter. |
| SQL catalog | Unchanged. `threads` stays in `KNOWN_EXCLUDED` and checkpoints stay closed, so no model-written SELECT reaches chat history. |
| PII | Chat text is the user's own and returned only to people who may open the thread. The title is the first question, stored on a row RLS already guards. |
| Secrets | None new. |

## 6. Testing

No new test files (repo practice for PRs). Existing tests are fixed only where a change breaks them, for example `claim_thread`'s signature in `test_security.py` / `test_access.py`.

Verification, by hand, against the compose stack:
- Ask a question, reload `/ask`, and reopen the chat: the turns, trace and rail are back.
- Ask a follow-up in the reopened chat: the answer uses earlier context, and the backend does not duplicate messages (`ag_ui_langgraph` dedupes by id, and the ids round-trip).
- Restart the frontend container and reopen: still there. Before, it was empty.
- Open the same chat signed in as another non-staff user: 404, and an empty chat.
- An Import chat does not appear in Recent Chats.
- A pre-migration chat with a null title shows its localStorage title, or "Untitled chat".

## 7. Milestones

#### Milestone 1: the backend saves a titled chat and serves it back
- **Deliverable**: `GET /api/threads` and `GET /api/threads/{id}/messages` work. New chats get a title.
- **Touches**: backend
- **Key tasks**: [ ] `claim_thread` / `list_threads` / `can_open` [ ] `_own_thread` passes the title [ ] `app.state.ask_graph` [ ] routes, schemas, router line
- **Acceptance criteria**: `cd backend && pytest -m "not integration" && ruff check .`; then `curl -H 'Authorization: Bearer dev' localhost:8010/api/threads/<id>/messages` returns the chat's messages.

#### Milestone 2: reopening a chat shows its messages
- **Deliverable**: picking a chat hydrates it, and follow-ups work.
- **Touches**: frontend
- **Key tasks**: [ ] `loadHistory` in `useAgentChat` [ ] `resume` through `AskWorkspace` → `ChatPane` → `useSangamChat` [ ] loading hint
- **Acceptance criteria**: `cd frontend && npm run lint && npm run build`; ask, reload, reopen, see the turns.

#### Milestone 3: Recent Chats comes from the server
- **Deliverable**: the list is the same on every browser.
- **Touches**: frontend
- **Key tasks**: [ ] `fetchThreads` [ ] title fallback [ ] refresh after the first send
- **Acceptance criteria**: `npm run build`; a chat asked in one browser profile shows in another, signed in as the same user.

## 8. Open questions and risks

- **Chats asked against another database stay invisible.** A chat asked while the backend pointed at local Postgres is not in staging, and vice versa. That is correct, but a localStorage title from the other database no longer shows. Example: Priya's local-only chat drops out of her staging list.
- **Old titles are null.** Rows from before this change have no title until the next turn in them. The frontend falls back to localStorage, then to "Untitled chat".
- **History size.** A long thread returns every tool result (some are long tables). This is acceptable for now; paging is a later concern.
- **A chat still running elsewhere.** Reopening a thread whose run is in flight in another tab shows the last checkpoint, not the live stream. It is acceptable and was never possible before.
- **Import reload** is deferred: replaying a paused human-in-the-loop run needs its own design.
