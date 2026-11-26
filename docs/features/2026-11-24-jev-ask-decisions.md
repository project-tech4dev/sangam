# Jev for Ask's decisions: route, skill and answer check

Status: **Draft v1**, 2026-11-24. Issue: #315 (epic #335). Supersedes nothing: `2026-11-13-classify-tags-typesafe.md`
(#405) is the tags plan and stays parked; the news classifier stays on #315 as its own track.

## 1. Goal

**Hand three of Ask's small decisions to TypeSafe's Jev, measure each one against what the model actually did, and act
only where the measurement says Jev agrees.** Success is a Langfuse score per decision showing agreement, latency and
cost, and then a skill read and an off-topic turn that no longer cost a model call.

Production, 10 Oct–24 Nov 2026 (the report at claude.ai/artifact/7K9T33DvuTH9rSsnQPZHW8):

| Decision | What happened | Jev's job |
|---|---|---|
| J1 route | 10 of 60 Ask turns were off-topic ("what is the weather today?") | say "off-topic" before the agent runs |
| J2 skill | 30 skill reads; 11 were a model call of their own (~2 s) | name the skill, so code preloads it |
| J3 answer check | Haiku marked 21 of 52 answers sound; nobody has checked it | the same verdict as calibrated yes/no |

Not Jev: tool gating (a guessed URL, #480; a save on a field rule, #479), escalation after a failed save, and goal
loops (Pitch's next section is the person's call). Each has a rule in code that is certain where Jev would guess.

## 2. Blast radius

Built by hand from `catalog.py`, CLAUDE.md's Architecture section and the Ask code; no table changes.

| Surface | Hop | Why affected | Status |
|---|---|---|---|
| `app/integrations/typesafe.py` | new | the one HTTP client | in scope |
| `app/ask/jev.py` | new | questions, labels, the middleware | in scope |
| `app/ask/agent.py` | 1 | registers the middleware | in scope |
| `app/ask/audit.py` | 1 | J3 reuses its evidence builder | in scope (M3) |
| `app/ask/instructions.md` | 1 | the model is told a skill may already be loaded | in scope (M1) |
| `app/integrations/tracing.py` | 1 | Jev's cost as a Langfuse generation | in scope |
| `app/core/config.py`, `.env.example` | 1 | settings, all off by default | in scope |
| `scripts/jev_replay.py`, `Makefile` | new | the offline measurement | in scope |
| Ask frontend | 2 | no change: a preload is not in the chat's messages, and an off-topic reply is an ordinary answer | unaffected |
| Import, Pitch, news | — | untouched | unaffected |
| SQL catalog, RLS | — | no table, no query | unaffected |

## 3. High-level design

```
 question ─▶ [J1+J2 before_agent]* ─▶ model ⇄ tools ─▶ answer ─▶ [audit: Haiku] ─▶ [J1/J2 shadow + J3]*
                │  off-topic, act: fixed reply, jump to end            after_agent, a score each
                │  skill, act: preloaded into this turn's model calls
                └─ TypeSafe POST /v1/systemone, one call, ~0.1–0.5 s          * new
```

- **Shadow runs after the answer**, so it adds no wait. It asks Jev the same questions the act mode would, then scores
  agreement with what the turn did: the skill the model read, and whether any data tool ran.
- **Act runs before the agent**, one Jev call with both questions. A preloaded skill goes into the model request, not
  the state: inserted after the question on every model call of the turn, so the turn's cache prefix holds and the
  chat never shows it. (A synthetic `read_file` call in state would be an assistant tool call with no thinking block,
  which Anthropic refuses; changing the system prompt per turn would break the chat's cache, as Pitch's does.)
- **Cost is visible:** each call is a Langfuse `generation` named `jev_route_skill` or `jev_audit`, with
  `usage_details` and `cost_details` (Langfuse has no price for `jev-*`, so it would show $0 otherwise).

## 4. Low-level design

**Settings** (`config.py`), all off by default:

| Setting | Values | Default |
|---|---|---|
| `TYPESAFE_API_KEY` | key | empty: no call is made |
| `JEV_MODEL` | `jev-latest` or a pinned version | `jev-latest` |
| `JEV_ROUTE` | `off` · `shadow` · `act` | `off` |
| `JEV_SKILL` | `off` · `shadow` · `act` | `off` |
| `JEV_AUDIT` | `off` · `shadow` | `off` |
| `JEV_ROUTE_THRESHOLD`, `JEV_SKILL_THRESHOLD` | 0–1 | 0.9, 0.8 |
| `JEV_USD_PER_MTOK` | input price | 0.042 |

**Client** `integrations/typesafe.py`: `decide(state, questions, *, name, settings) -> Decision | None`. Plain `httpx`,
3 s timeout, never raises. The response is `{model, usage: {input_tokens, output_tokens}, answers: {name: {type,
choice, confidence, probabilities} | {type, noul}}}` (typesafe-sdk 0.7.5's wire models). The SDK itself was not added:
it pulls `httpx2` for one POST.

**Questions** `ask/jev.py`:
- `route` (choice): `catalog` · `research` (find out about an org from the web, which is Scout's job) · `off_topic`.
- `skill` (choice): each skill's frontmatter description, plus `none`.
- `state`: `{question, previous_question}`, the question cut to 1,000 characters.
- J3 (M3): nouls `supported`, `grain`, `filters`, `false_zero`, `numbers` over `{question, evidence, answer}`, the
  evidence built by `audit.newest()`, so Haiku and Jev judge the same text.

**Scores** (Langfuse, per turn): `jev_route_agree`, `jev_skill_agree` (1 or 0, Jev's pick and probabilities in the
comment and metadata), `jev_route_acted`, `jev_skill_preloaded`, `jev_audit` (1 sound, 0 not).

## 5. Security review

- **Data sent to TypeSafe:** J1 and J2 send the question and the one before it. J3 sends the answer and the rows it drew
  on, which can include private org data under RLS, so `JEV_AUDIT` stays off until TypeSafe's terms are known. The
  person approved replaying all recorded questions (2026-11-24).
- **Secrets:** the key comes from the environment, goes only in the `Authorization` header, and never into a log or a
  span. The URL is ours, not model-supplied, so `guarded_client` is not needed.
- **Input:** a choice that is not one we asked for is ignored; a preload names a skill only from the skills folder.
- **No new route, table or catalog entry.**

## 6. Testing

- `tests/test_typesafe.py`: `httpx.MockTransport`: a 200 parses, a 401, 500 or timeout gives `None`, no key makes no
  call, usage is read or estimated, the key never reaches the log.
- `tests/test_ask_jev.py`: labels from hand-built turns (a skill read, none, data or no data), agreement, the preload
  insert, the off-topic jump, thresholds, `off` wiring nothing.
- One real local Ask turn per act mode before the next milestone, on the local database.

## 7. Milestones

Stacked, one PR each.

#### M0: shadow J1 and J2, plus the replay
- **Deliverable:** with `JEV_ROUTE=shadow JEV_SKILL=shadow`, every Ask turn gets two agreement scores and a `jev_route_skill`
  generation with its cost; `make jev-replay` runs the same questions over recorded production turns.
- **Acceptance:** `pytest tests/test_typesafe.py tests/test_ask_jev.py`; `make jev-replay` prints agreement, p50/p90
  latency, tokens and cost.

#### M1: act on J2, preload the skill
- **Deliverable:** with `JEV_SKILL=act`, a skill Jev names above the threshold is in the model request from the first call,
  and the model does not read it again.
- **Acceptance:** tests; a local "How well does KABIL fit Axis Bank Foundation?" turn with no `read_file` of the skill.

#### M2: act on J1, answer off-topic questions without the agent
- **Deliverable:** with `JEV_ROUTE=act`, an off-topic question above the threshold gets a fixed reply naming what Ask can
  do, with no model call; `catalog` and `research` go to the agent as now.
- **Acceptance:** tests; a local "what is the weather today?" turn ends with no generation but Jev's.

#### M3: J3, Jev's answer check beside Haiku's
- **Deliverable:** with `JEV_AUDIT=shadow`, each audited turn also gets `jev_audit` from the same evidence, and the
  replay compares it with the recorded `answer_audit` verdicts.
- **Acceptance:** tests; replay shows agreement with Haiku.

## 8. Open questions and risks

- **Data terms:** unknown; J3 stays off by default.
- **Latency in act mode:** the one call sits before the first model call. The replay's p90 says whether it costs more
  than the ~2 s a skill read saves.
- **Labels are the model's own behaviour**, not ground truth: agreement says Jev picks what the model picks, not that
  either is right. The off-topic label (no data tool ran) also catches a catalog question the model answered from the
  chat.
- **Thresholds** 0.9 and 0.8 are guesses until the replay's numbers.
