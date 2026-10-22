# Sangam Pitch: faster secondary research — Draft v2

Supersedes Draft v1 (same file, never committed), which launched a fixed three researchers from code. v2 lets a
supervisor decide how many, as discussed on 22 Oct.

## 1. Goal

**"Search public sources" finishes in about 3 minutes instead of 8, and the card shows what it is doing.**

Success: on proposal 6's inputs (InterGlobe Foundation, Better Life Foundation, Kiphire and Tuensang), on the **local**
stack, the fact list is done in under 180 s, every topic finds at least as many sources as today (problem 8, place 5,
government 5, SDG 2, elsewhere 6), and a run costs no more than today's $0.81.

## Where the 8 minutes go (measured, Langfuse trace of 22 Oct, 05:38)

| | today |
|---|---|
| wall time | 477 s |
| checking search hits, one after another | ~250 s: 18 searches, ~14 s of checks each |
| model calls | 32, one after another, in one agent; 147k tokens of context by the end |
| Tavily itself | 2–7 s a search |
| the brief (runs alongside, Anthropic's own search) | ~200 s |

> **The rule:** fix the waiting first, then the one-agent-does-everything.
> **Example:** a search for "Tuensang dropout rate" spent 3 s at Tavily and ~30 s checking ten hits in a queue
> (`access.check_url`: private address, registry, robots.txt, per hit).
> **Why it matters:** the first fix is five lines; the second is only worth it if the first is not enough.

## 2. Blast radius

Built by hand from `CLAUDE.md` and grep; there is no domain map.

| surface | hop | why affected | status | notes |
|---|---|---|---|---|
| `ingest/tools/research_tools.py::search_public_sources` | 1 | checks hits at once | in scope (M1) | Sangam Import's researchers get faster too |
| `proposals/readers.py` (`build`, `_one` for `PUBLIC`) | 1 | public research becomes a supervisor with researchers | in scope (M2) | file readers unchanged |
| `proposals/prompts/public_supervisor.md` | 1 | new: splits the work, launches researchers | in scope (M2) | — |
| `proposals/prompts/public_researcher.md` | 1 | works the angle its task names | in scope (M2) | one new section |
| `proposals/middleware.py` | 1 | new `ResearchProgress`: writes each researcher's line to `readers.public` | in scope (M2) | `PublicGuard`/`PublicRun` unchanged |
| `work.readers.public` (proposals.work JSON) | 1 | gains `slices: [{label, status}]` | in scope (M2) | no migration: it is JSON; `work.py:30` already accepts `readers.public` |
| Secondary research card (`ProposalShell.tsx`, `api.ts`) | 2 | one line per researcher while running | in scope (M2) | the missing progress indicator |
| `proposals/brief.py` | 1 | unchanged, still runs alongside | unaffected | becomes the slowest part after M2; see §8 |
| Step 2 file readers | 1 | unchanged | unaffected | already one per file |
| `agent/harness.py` | 1 | supervisor's subagent is declared, so no general-purpose one appears | unaffected | `install()` already disables it |
| Database, catalog, REST routes | — | nothing new is stored or exposed | unaffected | — |

## 3. High-level design (HLD)

```
 "Search public sources"
   readers.search()  ── background task (as today)
     │
     ├─ brief.write()                                 (as today, alongside)
     │
     └─ public supervisor  ◀── NEW, deep agent, RESEARCH_MODEL, tools: task only
          │  reads the task (places, themes, programmes, sections, focus)
          │  decides the angles: 2 to 5, e.g.
          │    "dropout and learning, Kiphire/Tuensang vs Nagaland vs India"
          │    "Nagaland and central schemes on secondary schooling"
          │    "what worked: community schools in the Northeast"
          │
          ├─ task → public-researcher (angle 1) ┐  one message, parallel
          ├─ task → public-researcher (angle 2) │  each: search_public_sources ◀── M1: checks hits at once
          └─ task → public-researcher (angle 3) ┘        read_page · fetch_document · read_document_pages
                                                        add_facts → repo.save (one transaction a save)
          │  each returns ≤ 10 lines: what it added, what it could not find
          └─ last message: what was found per topic, what is missing
```

Shared by all, unchanged: one `RunSources` (web only), one `PublicRun` (names never searched, pages read, hosts
refused), `PublicGuard` on every researcher, `add_facts`' quote check.

> **The rule:** the supervisor decides how many researchers and on what; code caps it.
> **Example:** a proposal in two districts with one theme gets 2 researchers; a focused "Look deeper" asking for SHG
> credit linkage, jhum cycles and NRLM coverage gets 3, one per angle; nothing ever gets more than 5.
> **Why it matters:** the split depends on the proposal, which code cannot see; the cap keeps Tavily and cost bounded.

**Key trade-off: a supervisor model, not a split in code.** It costs one model turn before the first search and one
after the last (~10–20 s, ~$0.05). In exchange the split fits the proposal and the person's focus, which a fixed
three-way topic split does not. It is the mechanism Sangam Import already uses (`entity-researcher` under its
supervisor, `ingest/agent.py:179`), built with `create_deep_agent` and the harness.

**Why the guards still hold.** deepagents runs parallel `task` calls as separate asyncio tasks, each copying the
context. `run_sources.CURRENT` and `PUBLIC_RUN` are set once before the supervisor runs, so every researcher sees the
same `Sources` and the same `PublicRun` object: a page one researcher read is quotable by `add_facts` from any.

## 4. Low-level design (LLD)

**M1 — `backend/app/ingest/tools/research_tools.py`** (`search_public_sources`, lines 128–134): check the shown hits
with `asyncio.gather(*(check_url(r.get("url", "")) for r in shown))`, then build the lines in the original order.
`check_url` never raises.

**M2 — `backend/app/proposals/readers.py`**
- `build`: `BUILT.public` becomes the supervisor:
  `create_deep_agent(model=research, tools=[], subagents=[PUBLIC_RESEARCHER], system_prompt=public_supervisor.md,
  middleware=[filesystem_tools(backend, evict=False), tool_errors(), ResearchProgress(), *fallback(...)])`.
- `PUBLIC_RESEARCHER = {"name": "public-researcher", "mode": "isolated", "tools": public_tools,
  "system_prompt": public_researcher.md, "middleware": [filesystem_tools(backend, keep=()), tool_errors(),
  RunSources(), PublicGuard(), *fallback(...)]}`. An isolated subagent inherits nothing, so it carries its own guards,
  as `ingest/agent.py` does.
- `_one`: unchanged apart from the graph it invokes; `public_task` is unchanged and goes to the supervisor.
- `MAX_RESEARCHERS = 5`, enforced by `ResearchProgress` (below), not by the prompt alone.

**M2 — `backend/app/proposals/middleware.py`**: `ResearchProgress(AgentMiddleware)`, on the supervisor:
- `awrap_tool_call` for `task`: refuses the sixth and later in a run ("five researchers are already running"); writes
  `readers.public.slices[i] = {label: description[:80], status: "running"}` before, `"done"`/`"failed"` after.
- Writes go through `repo.save` + `work.apply` on `readers.public` whole (the only path `_READER` accepts), inside
  the row lock fixed on `fix/pitch-read-imported`.

**M2 — prompts**
- New `proposals/prompts/public_supervisor.md` (~30 lines): split the five topics into 2–5 angles that fit this
  proposal; launch them all in one message; never search or read yourself; end with one line per topic: found, or
  what is missing.
- `public_researcher.md`: one section, "Your task names one angle. Find facts for it at every level; other angles are
  researched at the same time. End with at most 10 lines: what you added, what you could not find."

**M2 — frontend**: `api.ts` `Reader` gains `slices?: {label: string; status: string}[]`. `ProposalShell.tsx`
`SecondaryResearch` shows, while running:

```
Searching… started 1 min ago
  ✓ Dropout and learning in Kiphire and Tuensang · 9 sources
  ⋯ State and central schemes on secondary schooling
  ⋯ What worked: community schools in the Northeast
```

Counts come from the facts the 5 s poll already fetches. Styles as classes in `globals.css` from existing tokens; the
design system is updated in the same PR (`docs/DESIGN_SYSTEM.md`).

## 5. Security review

- No new endpoint, table, catalog entry or tool. `POST /api/proposals/{id}/research` keeps `require_edit`.
- The supervisor has no tools but `task`: it cannot search, read or write facts. Researchers keep every guard they
  have today (`RunSources`, `PublicGuard`, `check_url`, `add_facts`' quote check).
- The supervisor's task is today's `public_task`: places, themes, programmes, SDGs. No file, no fact list, never the
  organisation's name in a search (`PublicGuard` refuses it in each researcher).
- A test walks the compiled subagent graph, as `TestASubagentRunsOnlyTheToolsItsSpecDeclares` does: no
  `write_file`, `edit_file`, `execute`, and no general-purpose subagent.

## 6. Testing

Unit, no database:
- M1: a fake `check_url` that sleeps 0.2 s; ten hits finish in under 0.5 s and keep their order and HELD reasons.
- M2: the compiled supervisor has exactly `task` (+ the harness floor); the compiled `public-researcher` has exactly
  `PUBLIC_TOOLS` + `read_file`, with `PublicGuard` and `RunSources` in its middleware.
- M2: `ResearchProgress` refuses the sixth `task`; marks a slice running then done; marks it failed when the subagent
  raises; a failed write never fails the call.
- M2: two parallel fake researchers share one `PublicRun` (a page read by one is in `run.pages` for the other).
- `ProposalShell.test.tsx`: a running search lists each slice with its count; a run without `slices` (an old row)
  shows today's line.

Eval (costs money): one `TAG=pitch` case runs the search on a fixed proposal and records wall time, cost and sources
per topic.

## 7. Milestones

#### Milestone 1: search checks its hits at once
- **Deliverable**: `search_public_sources` returns in about the time of the Tavily call.
- **Touches**: backend
- **Key tasks**: [ ] gather `check_url` [ ] test order and concurrency
- **Acceptance criteria**: `pytest tests/test_cov_ingest_tools_research.py`; on the local stack, each search span in
  Langfuse is under 8 s and a full run is measured again. **If it is under ~4 min, decide then whether M2 is worth it.**

#### Milestone 2: a supervisor launches researchers, and the card shows them
- **Deliverable**: a search runs 2–5 researchers at once, chosen by the supervisor, each shown on the card.
- **Touches**: backend, prompt, frontend, design system
- **Key tasks**: [ ] supervisor + `public-researcher` in `build` [ ] `ResearchProgress` [ ] two prompts
  [ ] `slices` on the card [ ] tests
- **Acceptance criteria**: `pytest -m "not integration"`, `npm test`, `npm run build`; on the **local** stack the fact
  list is done in under 180 s with no topic emptier than today, at no more than $0.81.

## 8. Open questions and risks

- **The brief becomes the slowest part.** It takes ~200 s alongside, so after M2 the card waits on it. Options: the
  supervisor writes the brief from its researchers' findings (drops `brief.py`'s second web search and its context
  overflow), or the card shows the facts done while the brief finishes. Decide after M2 is measured.
- **Tavily is on the free plan**: 1,000 credits a month, 100 requests a minute. A run is ~18 credits; 20 at once is
  ~360. M2 makes bursts sharper. Moving to pay-as-you-go ($0.008 a credit) needs no code.
- **Production has never run a search.** `start_research` answers 202 and researches in `asyncio.create_task`; on
  Vercel a function may freeze after answering. Prove it with one run after the next Deploy, independent of this plan.
- **Duplicates across researchers.** Two angles may cite one NFHS fact sheet; `facts.same_as` drops identical facts,
  a near-duplicate stays. Acceptable for v1.
- **Cost.** The supervisor adds ~$0.05; each researcher's context is about a third of today's 147k, so the total
  should not rise. Measured in M2's acceptance.
