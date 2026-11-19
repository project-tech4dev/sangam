# Ask: 10 free questions for people outside an organisation (#314)

Status: Draft v1, 2026-11-20

## Why

Anyone can sign in with Google and use Ask Sangam. Each question runs `MODEL` (Opus) for up to
`ASK_MODEL_CALL_LIMIT=25` model calls. People in an organisation are the intended users; a signed-in
visitor with no organisation is just looking, and today nothing caps what they cost. That grows once
asksangam.org is public (#313).

## What

- **Metered:** signed in, not staff, no `org_members` row. Everyone else is unaffected.
- A metered person may ask **10 questions in total**. There is no monthly reset.
- At the limit they see: "You've used your 10 free questions. You can't ask new questions."
  No contact line, no link. Their past chats stay readable; the Registry and profiles stay open.
- Once someone adds them to an organisation, the limit no longer applies.

Non-goals: token or cost caps, a staff view or per-person override, a rate limit for everyone, a monthly
reset, a cost study. These go to a follow-up issue so #314 can close.

Constraint: **no new table.**

## Approaches

| | Trade-off | |
|---|---|---|
| New `ask_questions` table, one row per question | Supports a monthly reset and full history | Rejected: no new tables |
| Counter column on `users` | As small, but counts only metered people and nothing per chat | Rejected |
| **`threads.questions` column, bumped by `claim_thread`** | No extra write per question (claim_thread already writes the row every turn); counts everyone; no monthly reset | **Chosen** |

Counting chats, checkpoints or Langfuse was ruled out: a chat holds many questions, checkpoints are
pruned, and Langfuse is too slow to call per question and absent locally.

## Design

```
browser ── Ask composer ──► /api/copilotkit ──► POST /agent
   │  ★ "7 of 10 questions used"                   │
   │  ★ limit message replaces the composer        ▼
   │                                   ask_access (core/security.py)
   └── ★ /api/me free_questions               ├─ claim_thread ★ questions + 1
              │                           ├─ ★ metered and SUM >= limit → 429
              ▼                           ▼
        threads ★ questions column    Ask agent (unchanged)
```
★ = new

- **Migration:** `ALTER TABLE threads ADD COLUMN questions int NOT NULL DEFAULT 0`. Existing chats start
  at 0, so nobody is cut off on day one.
- **Counting:** `claim_thread` adds 1 per turn only for a metered caller (so a removed member starts at 0);
  a `CHECK (questions >= 0)` stops a self-inserted negative row cancelling the limit.
  Usage is `SUM(questions)` over all the person's threads: the thread id is the browser's to choose, so
  no id may be left out, and a metered person can use only Ask anyway. No route deletes a thread, so
  the count cannot be wiped.
- **Enforcing:** in `ask_access`, before `claim_thread`, for a metered caller: lock their `users` row
  (`FOR UPDATE`) in the same transaction as the sum and the bump, so two tabs at question 9 cannot both
  run. At the limit, 429 with the message above and no model call. A question counts when it starts,
  even if the run then fails.
- **Setting:** `FREE_QUESTIONS` in `core/config.py` and `.env.example`, default 10; `0` turns metering off.
- **No new endpoint:** `/api/me`, which the Ask screen already loads, gains
  `free_questions: {used, limit} | null`; null for staff, members, and when metering is off.
- **Ask screen:** metered people see "7 of 10 questions used" under the composer, refreshed after each
  answer. At the limit the composer is replaced by the message. A 429 that still arrives (a second tab)
  shows the same message, not a generic error. Styles in classes; the design system's Ask page updated.

## Milestones

**M1: Backend.** Migration, `claim_thread` bump, the check in `ask_access`, the setting, `/api/me`. Tests: metered vs staff vs member; 10th passes, 11th refused; two parallel requests at 9;
`/api/me` counts; limit lifts after joining an organisation.
Exit: tests green; on the local database the 11th POST to `/agent` is 429 with no model call.

**M2: Ask screen.** Both milestones ship as one PR. The usage line, the limit state, the 429 fallback, Vitest
tests, design system sync.
Exit: checked in Chrome as staff, member, and metered at 9 and at 10, and at phone width.

**After.** Follow-up issue for the rest of #314; close #314. ARCHITECTURE.md and CHANGELOG lines;
offer `make wiki-update`.

## Tasks

M1 (backend):
1. `db/migrations/0061_thread_questions.sql`: the column. (0058–0060 are taken on open branches.)
2. `config.py`: `free_questions: int = 10`, in the blank-means-default list; `.env.example` line.
3. `repositories/threads.py`: `claim_thread(..., limit: int | None = None) -> UUID | None` bumps
   `questions` only when given `limit`; then it locks the user row and returns None when `asked >= limit`.
   `asked(conn_or_pool, user_id) -> int` sums all their threads.
4. `core/security.py`: `_own_thread` computes the scope first; for an Ask turn by a metered caller
   (`not is_staff and not org_roles`, `free_questions > 0`) it passes `limit`, and None becomes 429
   with `FREE_QUESTIONS_SPENT`. Import and Pitch pass no limit.
5. `/api/me`: `free_questions` from `asked`. Tests in `test_access.py` and the me route's tests.

M2 (frontend): `MeOut.free_questions`; the usage line and the limit state in the Ask composer;
the 429 shown as the same message; Vitest; design system Ask page.

## Left to the builder

Where the 429's message is read on the frontend (CopilotKit's error path vs a pre-send check), and the
exact class names.
