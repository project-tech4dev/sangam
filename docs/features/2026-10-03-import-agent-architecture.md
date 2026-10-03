# Sangam Import: the agent architecture, and the funder/NGO split it has to carry

**Status: M0–M6 all built, 2026-10-03.** Four decisions were taken differently from the plan
below, each for a reason the building turned up:

- **D1 went one tool further.** The parent also loses `research_goals`. M5 makes it
  required-kind and refuses `"unknown"`, and a supervisor that has not read a source can only
  ever guess `"funder"` — F6 one hop up. It ends at seven, not eight.
- **M5's `kinds` split is not "the existing 13 become funder-only".** `program`, `metric`,
  `contact` and `document` each carry an `org_id` as well as a `funder_id`, so they stay both
  and only the foreign key changes. `identity` and `identifier` flip to funder-only, which is
  the actual F6 bug.
- **`render_docs.py` needed no unclassified heading.** The live rows were 16 funder complete,
  21 funder partial and one `unknown` that is a `wrong_entity` — an organisation we rejected,
  listed to clients as a funder. `== "funder"` is the fix, and the run now prints what it left
  out.
- **M6 also removes `ls` from both subagents.** With no skill declared, `ls` is dead weight
  pointing at the one backend route that is real disk.

One thing listed as open was left open: `milestonesOf` still returns five buckets, not four.
 Written 2026-10-03, branch `feat/import-agent-architecture`,
stacked off `feat/supabase-storage` — from it, not onto it, because the Import UI components
only exist there. This is a record of what was decided and why, not a description of what
exists. When the code lands, the living description goes in `docs/INGEST.md`; this file stays
as the reasoning.

---

# Part 1 — Goals

## Why this grew past "classify NGOs"

The ask was two things: a quieter run screen, and an agent that works out whether a name is a
funder or an NGO. Mapping the agent to plan that turned up four problems underneath, one of
which is a security bug. Three of them are *in the way* of the funder/NGO split:

- Adding four org concepts means editing the concept vocabulary in **seven** places, one of
  which has no test under it — and that one has already silently dropped data.
- Classification has to be owned by one agent, and today the parent and the researcher can both
  call the tool that would do it.
- An NGO brief needs an output procedure, which is what the skills mechanism is for — and the
  one skill that exists is funder-shaped and declared on the wrong agent.

So this is one plan: fix the structure, then land the split inside it.

## What we want to be true

1. **A subagent cannot write to disk.** The tool list each subagent actually runs with is the
   one its spec declares, and a test proves it on the subagent graph, not the parent's.
2. **The concept vocabulary has one source of truth.** Adding a concept is one entry; the
   table, the model, the title, the writer and the promotion excuse all derive from it, and
   nothing can be half-added.
3. **The parent supervises; the researcher researches.** One path to a source, under the
   instructions written for it.
4. **The run screen shows stages, not steps**, and a line appears only on a refusal or failure.
5. **The agent decides funder-or-NGO before it spends budget**, states the reason, shows it on
   screen, and researches an NGO against the org tables — 12A, 80G, FCRA, Darpan, legal form,
   total income, programme spend, foreign contribution, districts.
6. **Nothing already saved breaks.** The 36 research rows keep promoting and keep rendering.

---

# Part 2 — Inventory

Everything in this section was read or executed, not inferred. The two introspections are
reproduced in Verification.

## Tool registration, as built

Parent `TOOLS` is 13 (`agent.py:98-118`); the graph advertises **16**, because
`SubAgentMiddleware` adds `task` and the harness filesystem middleware adds `read_file` and
`ls`. `instructions.md:211` says "Thirteen", and names none of the other three.

| Tool | Module | Parent | researcher | writer |
|---|---|---|---|---|
| `list_import_sources` · `plan_import` · `run_import_now` · `import_run_summary` · `pending_resolutions` | `pipeline_tools.py` | ✓ | | |
| `research_goals` | `catalog_tools.py:174` | ✓ | ✓ | |
| `funder_dossier` | `catalog_tools.py:29` | ✓ | ✓ | ✓ |
| `promote_research` | `catalog_tools.py:266` | ✓ **writes** | | ✓ **writes** |
| `search_public_sources` · `read_page` · `fetch_document` · `read_document_pages` | `research_tools.py` | ✓ | ✓ | |
| `save_research` | `research_tools.py:198` | — | ✓ | |
| `publish_brief` | `research_tools.py:304` | ✓ | | |

Nothing is defined-but-unregistered. The parent holds every research tool *and* the promotion
tool, duplicating both subagents.

## The concept vocabulary, written out seven times

| List | Where | Checked against the hub? |
|---|---|---|
| `CONCEPT_TABLES` | `expectations.py:23` | — the hub, 13 entries |
| `CONCEPTS` | `research_records.py:26` | ✓ `test_ingest.py:483` |
| `FINDING_MODELS` | `research_records.py:382` | ✓ `:562` |
| `PROMOTABLE` | `promote.py:65` | ✓ `:738` (12; `grant` excluded) |
| `NOT_WRITTEN` | `promote.py:113` | ✓ via `:818` |
| `Concept` (Literal) | `research_records.py:30` | ✗ dead — imported nowhere |
| `CONCEPT_TITLES` | `brief.py:17` | ✗ **imported by no test** |

## Prompts, by line count

| File | Lines | Runs on | Sees a source? |
|---|---|---|---|
| `instructions.md` | 239 | parent | no |
| `prompts/entity_researcher.md` | 17 | entity-researcher | **yes** |
| `prompts/catalog_writer.md` | 11 | catalog-writer | no |
| `skills/funder-scan-for-fundraisers/SKILL.md` | 76 | whoever loads it | — |

The researcher is `mode="isolated"`: it never sees `instructions.md`.

## Budgets

| Limit | Value | Enforced by |
|---|---|---|
| searches / documents per researcher | ~8 / ~6 | **prose only** (`entity_researcher.md:9`) |
| fan-out wave | 8 (`MAX_PARALLEL_RESEARCH`) | **prose only** (rendered into `instructions.md:166`) |
| recursion | 200 steps, **per subagent invocation** | code (`config.py:88`) |
| context | clear tool results at 40 000 tokens | code (`middleware.py:30`) |
| page text / PDF text / download | 8 000 ch / 12 000 ch / 60 MB | code (`research_tools.py:32-34`) |
| adapter concurrency | 7 | code (`runner.py:101`) — the adapter path only, not fan-out |

## Models

Everything runs on `settings.model` (`anthropic:claude-sonnet-5`) out of the box.
`catalog-writer` is the only component that can be downgraded, via `UTILITY_MODEL`
(`agent.py:188-189`), and it is empty by default. The researcher is deliberately on the full
model — it reads forty-page annual reports.

---

# Part 3 — Findings, ranked

### F1 — Both subagents can write to disk. **Verified by execution.**

`harness.py:50-52` and CLAUDE.md both state that nothing which writes survives on either agent.
On the parent that is true. On the subagents it is false.

`create_deep_agent` builds an isolated subagent's middleware from scratch
(`deepagents/graph.py:689-702`) with `FilesystemMiddleware(backend=backend, …)` and **no
`tools=`**, which the library resolves as "all tools opted in". The parent's custom middleware
is only folded in when `is_forked` (`graph.py:729-732`); both Sangam subagents are
`mode="isolated"`, so `keep=SKILL_READING_TOOLS` never reaches them.

Built and introspected:

```
entity-researcher -> delete, edit_file, execute, fetch_document, funder_dossier, glob, grep,
                     ls, read_document_pages, read_file, read_page, research_goals,
                     save_research, search_public_sources, write_file      (15, not 7)
catalog-writer    -> delete, edit_file, execute, funder_dossier, glob, grep, ls,
                     promote_research, read_file, write_file               (10, not 2)
```

**Blast radius, measured not assumed.** `execute` is **inert** — the default backend is
`StateBackend`, not a `SandboxBackendProtocol`, so it raises `NotImplementedError`. `glob` and
`grep` are read-only enumeration. Three are live: `write_file`, `edit_file`, `delete`, and only
against the `/skills/` route, because that is the one route on the `CompositeBackend`
(`agent.py:90-93`) backed by real disk. Proved in a temp directory:

```
b.write('/skills/demo/SKILL.md', 'OVERWRITTEN BY SUBAGENT\n')  → WriteResult(error=None)
file on disk now reads: 'OVERWRITTEN BY SUBAGENT\n'
b.delete('/skills/demo/SKILL.md')                              → file gone
```

Target is `backend/app/ingest/skills/` — which `make up` bind-mounts from your working tree. The
agent that holds these tools is `entity-researcher`, the one that reads untrusted web pages, and
the file it can rewrite is advertised into every later thread. On Vercel the filesystem is
read-only outside `/tmp`, so this fails there and writes your working tree locally.

`test_harness.py:116-124` cannot catch it: it inspects `build(...).nodes["tools"]`, the parent
graph, and never a subagent graph.

### F2 — One concept list has no test under it, and it has already lost data

Six of the seven lists above are pinned to `CONCEPT_TABLES`. `CONCEPT_TITLES` (`brief.py:17`) is
imported by no test. It has 12 entries against the hub's 13; the missing one is `rfp`.

`brief.py:140` iterates `CONCEPT_TITLES`, not the findings, so a concept with no title is
dropped silently. `TestRfpIsNowAConcept` (`test_ingest.py:926-930`) asserts `rfp` has a table, a
model and a writer — and never that it has a title. **Every RFP finding ever saved is invisible
in every brief**, which is the one concept `instructions.md:71` calls "the one an NGO can act on
this week".

Adding four org concepts means seven edits with one unguarded.

### F3 — The prompts are inverted

The 239-line `instructions.md` runs on the parent, which never opens a page. The 17-line
`entity_researcher.md` runs on the only agent that does — and because it is `mode="isolated"`
it never sees `instructions.md` at all. The access rules get one clause in those 17 lines; the
source-priority tiers get a parenthesis. Meanwhile the parent carries 14 extraction concepts and
a full source-tier table it will never use.

### F4 — The parent duplicates both subagents

The parent holds all six research tools and `promote_research`. This is deliberate
(`instructions.md:181-182, 194-195`: don't delegate for a single organisation) — but it is the
same shape CLAUDE.md already rejected once, when `search_orgs` and `db_query` were two paths to
the same rows and drifted apart. These two have already drifted: a parent researching directly
runs under `instructions.md`, without the researcher's budget, entity-confirmation and
money-unit paragraphs.

### F5 — The one skill straddles both agents and half-duplicates a tool

`funder-scan-for-fundraisers` is two things: a field list to chase, and an output/comparison
format. The field list is what `research_goals` already derives from the schema. The output
format can only be produced by the **parent**, since the researcher returns a `ResearchSummary`
with no prose. Yet `ENTITY_RESEARCHER` re-declares `skills` (`agent.py:149`) and the parent is
the one that writes the comparison.

### F6 — Classification is not a step anywhere

No code classifies. `EntityResearch.entity_kind` defaults to `"unknown"`
(`research_records.py:398`) and is backfilled at save time; `research_goals` defaults to the
opposite, `"funder"` (`catalog_tools.py:174`), and `instructions.md:213` does not document the
parameter, so the default always wins. All six rows from the 1 Oct run are unresolved.

An NGO does not merely get a shorter list — it gets the wrong one: `funder_type`,
`section_135_bound`, `parent_name`, and an identifier enum of
`pan|cin|csr1|darpan|reg_no|domain|name`. **12A, 80G and FCRA are not in it.** `org_identifiers`
carries all three and nothing points research at it.

### F7 — The run view is a wall of text

One line per tool call. Structural: AG-UI streams a subagent's tools as the parent's work
(`milestones.ts:5-11`), so every parallel researcher's reads flatten into one list.

### F8 — Smaller things, carried but not led with

- `instructions.md:211` says "Thirteen"; the surface is 16. `read_file` and `ls` are the skill
  loader and are documented in no prompt.
- Three names for one agent: AG-UI `sangam_ingest`, Langfuse `sangam_import`, path `/ingest`.
- `docs/INGEST.md`'s "Known gaps" is stale in three entries — rfp, the ten statutory items and
  the parent link are all now pinned as working by tests (`:926`, `:848`, `:858`). Its line 181
  says "Twelve concepts"; there are 13.
- The library injects ~40 lines of skills boilerplate on every request, including an
  "Executing Skill Scripts" section for a tool that is inert here.

---

# Part 4 — Decisions

Each states the alternative and what it costs, so the shape can be argued with.

### D1 — The parent becomes a pure supervisor

Remove the six research tools and `promote_research` from `TOOLS`. The parent keeps the five
pipeline tools, `research_goals`, `funder_dossier` and `publish_brief` — enough to plan, to say
what is held, and to re-publish.

*Alternative:* keep them, so one organisation needs no `task` hop.
*Cost of removing:* a single-organisation run gains one hop. The screen does not change —
AG-UI streams subagent tools inline anyway.
*Why removing wins:* two paths to the same work is what CLAUDE.md killed with `search_orgs`, and
these two already behave differently, because only one of them runs under the researcher's
budget and entity-confirmation rules.

### D2 — One concept registry; the other six lists derive

A single table of concept records — table, model, title, promotable, excuse, which entity kinds
offer it — in `expectations.py`. `CONCEPT_TABLES`, `CONCEPTS`, `FINDING_MODELS`, `PROMOTABLE`,
`NOT_WRITTEN` and `CONCEPT_TITLES` become derived views over it, keeping their names so the five
existing invariant tests stay meaningful.

*Alternative:* add a seventh hand-maintained list and a test for it.
*Cost:* one refactor touching four modules, against four more concepts arriving in M5 and the
org writer's concepts arriving later.
*Note:* the dead `Concept` alias (`research_records.py:30`) is deleted, not derived.

### D3 — Skills are the parent's output procedures; the researcher declares none

The researcher's targets come from `research_goals`, which derives them from the schema and
cannot go stale. Skills carry what the schema cannot: how to lay out a comparison a fundraiser
can act on. So `ENTITY_RESEARCHER` drops its `skills` key, and the NGO equivalent of the funder
scan becomes a second skill on the parent.

*Alternative:* keep skills on the researcher.
*Cost:* the researcher loses the ability to load a brief format it cannot output anyway.
*Constraints:* `docs/SKILLS.md`'s "worth a round trip" rule, and `test_harness.py:201` requires
`"use when"` in a description.

### D4 — Budgets stay prose for now; M1 ships the mechanism that would enforce them

The subagent `middleware` key that fixes F1 is the same hook a step-counting middleware would
use (the shape of `sql_retry_limiter`, `app/agent/middleware.py`). Build the hook, not the
budget.

*Alternative:* enforce ~8 searches now.
*Cost of waiting:* the only real ceiling stays `recursion_limit=200` per subagent, ~25× the
prose budget. Listed in Known gaps.

### D5 — The researcher owns classification; `"unknown"` is refused, not served

`entity_researcher.md:5` already mandates a confirming search before any budget is spent, and
that one search answers *is this the right KABIL* and *funder or NGO* together. With D1 the
parent cannot research, so ownership is unambiguous and the chips cannot double.

`research_goals` with no kind, or `"unknown"`, returns a correctable error naming the rule.
*Alternative:* return both goal sets.
*Cost of that:* ~1.5× the longest tool result dumped at step 1, it lets the model dodge the
decision permanently, and for an NGO it reproduces today's wrong list.
`"unknown"` survives as a save-time value for `not_found` / `wrong_entity` rows, and because the
DB CHECK and legacy rows need it readable.

### D6 — `SCHEMA_VERSION` stays at 2

`promote.py:578` and `brief.py:132` both gate on `row["schema_version"] < SCHEMA_VERSION`.
Bumping to 3 strands all 36 saved rows: every one becomes "re-run the research" at promote, and
every existing brief gets that stamp on the next `make client-docs`. Adding concepts changes no
existing shape. A standalone test carries the reason.

---

# Part 5 — The target shape

```
                      user: "Bosch, Arpan, Rohini Nilekani"
                                      │
                        ┌─────────────▼──────────────┐
                        │      SANGAM IMPORT         │  supervisor — researches nothing
                        │  instructions.md           │  tools: 5 pipeline · research_goals
                        │  skills: funder-scan,      │         funder_dossier · publish_brief
                        │          ngo-brief         │  waves of {{MAX_PARALLEL_RESEARCH}}
                        └─────────────┬──────────────┘
                                      │ task(entity-researcher, name) ×N
                                      │ mode=isolated — inherits no prompt, no tools
        ┌─────────────────────────────┼─────────────────────────────┐
        ▼                             ▼                             ▼
 ╔══════════════╗              ╔══════════════╗             ╔══════════════╗
 ║  researcher  ║              ║  researcher  ║             ║  researcher  ║
 ║   "Bosch"    ║              ║   "Arpan"    ║             ║  "Rohini N." ║
 ╚══════╤═══════╝              ╚══════╤═══════╝             ╚══════╤═══════╝
        │  tools: 7 + read_file + ls      ← M1: declared, not inherited
        │  prompt: entity_researcher.md   ← M4: gains the access rules and source tiers
        │
 ┌──────▼──────────────────── STEP 1: RESOLVE ───────────────────────────────┐
 │  search_public_sources("<name>")   — ONE search, no document reads        │
 │    a) is this the organisation asked for?   wrong → STOP, wrong_entity    │
 │    b) does it GIVE money or RECEIVE it?                                   │
 │       BSE/NSE · MCA · csr.gov.in · CSR annexure      → funder             │
 │       NGO-Darpan · GuideStar India · 12A/80G page    → org                │
 └──────────────────────────────┬────────────────────────────────────────────┘
                                │ states the kind AND the reason
               ┌────────────────┴─────────────────┐
       funder  │                                  │  org
               ▼                                  ▼
 ┌─────────────────────────────┐    ┌─────────────────────────────┐
 │ research_goals(name,        │    │ research_goals(name,        │
 │               "funder")     │    │               "org")        │
 │ looks up  funders  [funder:N│    │ looks up  orgs     [org:N]  │
 │ held      WHERE funder_id   │    │ held      WHERE org_id      │
 ├─────────────────────────────┤    ├─────────────────────────────┤
 │ 13 concepts                 │    │  8 concepts                 │
 │   identity · identifier     │    │   org_identity   → orgs     │
 │   csr_year · csr_spend      │    │   org_identifier → 12a·80g  │
 │   footprint · partner       │    │                    ·fcra    │
 │   stated_geography · grant  │    │   org_financials → income,  │
 │   rfp · program · metric    │    │      programme spend, FC    │
 │   contact · document        │    │   org_location   → district │
 │                             │    │   program · metric          │
 │                             │    │   contact · document        │
 └──────────────┬──────────────┘    └──────────────┬──────────────┘
                │   ── ONE registry entry each (D2) ──┘
                │   funder_dossier · search · read_page · fetch_document
                ▼
       save_research(findings)
       ├─ INSERT entity_research  (entity_kind, findings jsonb, goals)
       └─ publish brief → Supabase Storage + docs/entities/<slug>.md
                │
                ▼  ResearchSummary{…, entity_kind}  → back to the supervisor
   ┌────────────┴────────────┐
   │ funder                  │ org
   ▼                         ▼
 task(catalog-writer)   NO catalog-writer
   │  tools: 2 + read_file   "orgs has no writer yet — this stays research"
   ▼                          (promote.py:565-575 — the guard stays)
 promote_research → funders · funder_identifiers · _csr_years · _csr_spend ·
                    _footprints · _locations · _partners · programs ·
                    metrics · contacts · documents · rfps
```

---

# Part 6 — Milestones

Ordered by what unblocks what. **This differs from the original sketch**: the quiet UI moved
from first to third. It is still independently shippable and touches no backend — but F1 is a
security bug with a one-line-per-subagent fix, and the key it adds is what M4's budget hook
would later use, so it goes first.

## M0 — this document

Commit to `docs/features/2026-10-03-import-agent-architecture.md`, per
`docs/features/2026-09-30-supabase-storage.md`.
**Exit gate:** `git checkout -b feat/import-agent-architecture feat/supabase-storage`, committed.
**Then stop for shape review.**

## M1 — a subagent runs the tools its spec declares

`agent.py`, `test_harness.py`, plus three docs the current wording falsifies.

- Add a `middleware` key to both subagent specs — the library's documented escape hatch
  (`deepagents/middleware/subagents.py:102-105`):
  `ENTITY_RESEARCHER` → `[filesystem_tools(backend, keep=SKILL_READING_TOOLS)]`;
  `CATALOG_WRITER` → `[filesystem_tools(backend)]`, which is `keep=("read_file",)`, the floor
  `FilesystemMiddleware` refuses to be built below.
- Both specs are built from a `backend` that only exists inside `build_ingest_agent`, so the
  specs become functions of it, or the middleware is attached in the builder beside the existing
  `writer = {**CATALOG_WRITER}` copy (`agent.py:187`). Prefer the latter — it keeps the
  module-level dicts importable, which `test_harness.py:223` and `:126` depend on.
- The library's default also passes `_permissions=spec.get("permissions", permissions)`. Both are
  `None` here, so replacing the middleware loses nothing — state that in the commit.
- **A test that inspects the subagent graph, not the parent's.** `test_harness.py:116-124` is
  blind to this. Look for a stable attribute on `SubAgentMiddleware` holding the compiled
  subagents first; if there is none, walk the `task` tool's closure with a comment naming
  deepagents 0.7.16, because the next upgrade may move it.
- Docs this falsifies, all to be corrected in this milestone: CLAUDE.md ("Nothing that writes
  survives on either", "Tests pin all of it"), `docs/SKILLS.md:79-82`, and the `harness.py:50-52`
  docstring.

**Exit gate:** the introspection in Verification prints 9 tools for the researcher and 3 for the
writer, with no `write_file`, `edit_file`, `delete` or `execute` on either; the new test fails
when the `middleware` key is removed.

## M2 — one concept registry

`expectations.py`, `research_records.py`, `promote.py`, `brief.py`, `test_ingest.py`.

- **Write the failing test first:** `set(CONCEPT_TITLES) == set(CONCEPT_TABLES)` fails today on
  `rfp`. That proves F2 before the registry exists and becomes the registry's first invariant.
- One record per concept carrying table, finding model, brief title, promotable, the
  `NOT_WRITTEN` excuse, and the entity kinds that offer it. The six lists become derived views
  under their existing names, so `test_ingest.py:483, 562, 738, 818` keep meaning something.
- Delete the dead `Concept` alias (`research_records.py:30`).
- Give `rfp` a title and a `headline()` branch (`brief.py:63-108`) — without a branch it falls
  through to the generic join at `:108` and prints a raw dict.

**Exit gate:** `pytest backend/tests/test_ingest.py` green with no DB and no network; adding a
concept with a missing title fails a test rather than vanishing from briefs.

## M3 — a quieter run view (frontend only, ships alone)

- `ImportWorkspace.tsx` — delete the `turn.steps.filter(...).map(...)` block at **64-93**;
  replace with a failures-only strip gated on `stepNote(step.result)`
  (`toolLabels.ts:83-89` already matches exactly `REFUSED:` / `ERROR:` / `… failed:`). A clean
  run renders nothing. Keep `humanizeTool` on survivors.
- `components/RunStatus.tsx:42-46` becomes the only live signal and today prints the raw tool
  name — use `humanizeTool`.
- `lib/milestones.ts` — bucket 1 relabelled "Identified", chips become `name → KIND` from
  `(s.args as any)?.entity_kind`. **Dedupe by name, not the joined string**: `:74-76` uses a
  `Set` over bare names, and once a kind is attached two calls for one organisation render
  twice. Build a `Map<name, kind>` and let a real kind overwrite a missing one. Until M5 the
  kind is absent and the chip falls back to the bare name — safe to ship first.
- `components/ResearchShelf.tsx:48-50` — show `entity_kind` as a badge. Already on
  `ResearchRecord` (`lib/types.ts:53`) and already returned by `/api/ingest/research`
  (`schemas/ingest.py:72`); never displayed.
- **On the count:** the request said four buckets; `milestonesOf` returns **five**. Only bucket
  1 changes here. To get to four, `catalog-write` is the one to drop, since nothing is promoted
  today.

**Exit gate:** `npm run lint && npm run build` clean; a run shows the strip, the status pill and
no per-source lines; a `HELD` source still shows its refusal.

## M4 — the supervisor stops researching, and the prompts swap weight

`agent.py`, `instructions.md`, `prompts/entity_researcher.md`, `toolLabels.ts`.

- Remove the six research tools and `promote_research` from `TOOLS` (D1). `RESEARCH_TOOLS`
  stops being an intermediate constant and becomes the researcher's list.
- Move the access rules, the source-priority tiers and the usability rules from
  `instructions.md` into `entity_researcher.md` — the agent that actually reads sources. The
  parent keeps delegation, output, promotion semantics and the registry of what exists.
- Fix `instructions.md:211`: the surface is 16, and `read_file`/`ls` are the skill loader.
- **Test-fenced — name these in the PR.** Six literal-substring assertions on `instructions.md`
  (`test_ingest.py:269, 283, 288, 338, 772`, and `:803` on a docstring), plus `:250`/`:256`
  requiring every registered tool to be named there. Moving a tool off the parent changes what
  `:250` iterates; moving prose must preserve or deliberately update the rest.

**Exit gate:** `test_ingest.py` green; a single-organisation run still completes, now via one
`task` hop; the researcher's prompt contains the access rules.

## M5 — entity kind, end to end

`expectations.py`, `research_records.py`, `catalog_tools.py`, `prompts/`, `instructions.md`,
`render_docs.py`.

- **Four org concepts as registry entries** (D2 makes this one edit each):
  `org_identity → orgs`, `org_identifier → org_identifiers`,
  `org_financials → org_financials`, `org_location → org_locations`, with
  `kinds={"org"}`; the existing 13 get `kinds={"funder"}`. `concepts_for(kind)` reads the
  registry. Namespacing is forced, not chosen: `Finding` is a tagged union on `concept`
  (`research_records.py:375-380`) and two members cannot both declare `Literal["identity"]`.
  - Do **not** map `org_tags` — `tag_id` is dropped as a bare `_id`, so the concept would have
    no field naming its subject.
  - `orgs` has **no `website`**; `EntityResearch.website` already carries it at the envelope
    level, and `test_the_model_carries_exactly_what_the_table_expects` compares field sets
    exactly.
  - Use `Money` for all four amounts even though the columns are `numeric` — the test compares
    names, and a bare float reintroduces the crore bug on a new surface.
- `concepts_for("org")` returns the four plus `program`, `metric`, `contact`, `document` — eight,
  against a budget of about eight searches. All four carry `org_id`, so they become promotable
  the day an org writer lands. Going leaner is one registry field.
- **`research_goals(name, years, entity_kind)`** — required, no default, refuses `"unknown"`
  (D5). Look up `orgs` for kind=org and print `[org:N]`; fix the no-match copy at `:212`, which
  tells an NGO researcher "That is not evidence the funder is absent".
- **The bug this milestone must not ship:** `_held_per_concept` (`:245-257`) iterates
  `CONCEPT_TABLES` and emits `WHERE funder_id = %s`. The moment org tables are in that map it
  becomes `SELECT … FROM orgs WHERE funder_id = %s` → `UndefinedColumn`, swallowed by the broad
  `except` at `:240` — **for funder runs too**, because the loop runs before anything is
  printed. Signature becomes `_held_per_concept(conn, entity_id, entity_kind)`, iterating
  `concepts_for(kind)` with the FK chosen by kind.
- `funder_dossier(name, entity_kind="funder")` — a parameter, not a second tool. A new
  `org_dossier` would join two tool lists, `instructions.md`, `toolLabels.ts` and
  `milestones.ts:24`, and leave the model two near-identical tools.
- `EntityResearch.entity_kind` (`:398`) loses its default and gains a `model_validator` in the
  style of `_complete_means_something_was_found` (`:423`): `complete`/`partial` with
  `"unknown"` is a contradiction. `ResearchSummary.entity_kind` becomes required — not for the
  UI (the shelf reads the saved row) but so the supervisor knows **not** to launch a
  catalog-writer for an NGO, which today burns a subagent to produce only a refusal.
- `entity_researcher.md` — fold resolve → classify-and-say-why → `research_goals(kind)` into one
  ordered step. A wrong *entity* is still a STOP; a wrong *kind* is just a different goal list.
- `render_docs.py:107` — `!= "org"` → `== "funder"`, but **check the rows first**:
  `select entity_kind, count(*) from entity_research group by 1;`. `"unknown"` is today's
  default, so flipping the test silently drops those files on the next `make client-docs`.
  Render them under an "unclassified" heading instead.
- The org promotion guard (`promote.py:565-575`) **stays**, with four registry excuses behind it.

**Exit gate:** a live run on a mixed list classifies both, saves `entity_kind`, launches no
catalog-writer for the NGO; `expected_fields("org_identifier")` offers 12a/80g/fcra.

## M6 — the skills the parent actually needs

- `ENTITY_RESEARCHER` drops its `skills` key (D3).
- Add `skills/ngo-brief-for-funders/SKILL.md` — the org-side counterpart: what a funder wants to
  see about an NGO. Description must open with "use when" (`test_harness.py:201`) and say what
  it is **not** for.
- Re-check SKILLS.md's own rule afterwards: ask something unrelated and confirm no `read_file`
  appears in the trace.

**Exit gate:** both skills discovered; neither loads on an unrelated turn.

---

# Part 7 — Known gaps this does NOT close

- **Promoting NGO research into `orgs`.** No `OrgRecord`, no `resolve_org`, no `write_org`.
  `docs/INGEST.md:287-288` lists it; `grants` waits on it. The natural next PR, and roughly the
  size of everything above.
- **Budgets stay prose.** ~8 searches and 8-wide fan-out are still the model's self-discipline;
  the only hard ceiling is `recursion_limit=200` per subagent (D4).
- **Three names for one agent** — AG-UI `sangam_ingest`, Langfuse `sangam_import`, path
  `/ingest`. Noted, not fixed; renaming moves a mount path and a trace history.
- **`docs/INGEST.md` is stale** in three gap entries and its concept count. Fixed in M2's
  commit as documentation, not re-litigated here.
- **The library's ~40 lines of skills boilerplate** ship on every request, including an
  "Executing Skill Scripts" section for a tool that is inert here. Not ours to remove.

---

# Part 8 — Verification

**Prerequisite.** `/import` cannot be opened right now — the frontend 500s on every route
because `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` is empty in `.env` (the URL is set; the key is
likely still under the old `NEXT_PUBLIC_SUPABASE_ANON_KEY` name). Fix that and `make up` first,
or a pre-existing 500 reads as a regression.

```bash
make up
cd backend  && pytest -m "not integration"
cd frontend && npm run lint && npm run build
```

**The M1 introspection**, which is also how F1 was proved — it builds the real graph and walks
the `task` closure:

```bash
cd backend && ANTHROPIC_API_KEY=dummy .venv/bin/python -c "
from app.core.config import Settings
from app.ingest.agent import build_ingest_agent
g = build_ingest_agent(Settings(anthropic_api_key='dummy'), None)
task = g.nodes['tools'].bound._tools_by_name['task']
for cell in (task.func.__closure__ or ()):
    c = cell.cell_contents
    if isinstance(c, dict):
        for k, v in c.items():
            if hasattr(v, 'nodes') and 'tools' in getattr(v, 'nodes', {}):
                print(k, '->', sorted(v.nodes['tools'].bound._tools_by_name))
"
```

Before M1: 15 and 10 tools. After: 9 and 3, with no `write_file`, `edit_file`, `delete` or
`execute`.

**The /skills/ write proof** (temp directory, touches no repo file) is in F1 and should become a
regression test: a `CompositeBackend` with a `FilesystemBackend` route accepts `write` and
`delete` against that route.

Then at `localhost:3000/import`, one run over `Bosch, Arpan, Rohini Nilekani Philanthropies`:

1. The strip shows `Bosch → FUNDER`, `Arpan → NGO`, and **no** per-source lines.
2. Point one name at a `HELD` source; the refusal still appears.
3. ```
   docker compose exec -T postgres psql -U sangam -d sangam -c \
     "select entity_name, entity_kind, fact_count,
             jsonb_path_query_array(findings, '\$[*].concept')
        from entity_research order by id desc limit 3;"
   ```
   The NGO row is `org` with `org_*` concepts; neither row is `unknown`.
4. No catalog-writer card on the board for the NGO.
5. `make client-docs`, then read the NGO's `docs/entities/<slug>.md` — org sections render, no
   raw dicts; a funder brief with an RFP now shows it.
6. Offer promotion on the NGO: refused, naming the held concepts. On a funder: still writes.

---

# Part 9 — Out of scope

- **Splitting the adapter path into its own agent.** The five pipeline tools are a different job
  from research and arguably a different agent. Real, and much larger than this.
- **Renaming to one agent name.**
- **A code-enforced research budget** — mechanism in M1, policy later (D4).
- **The org writer** — the gap in Part 7.

---

# Part 10 — Files

| File | M | Change |
|---|---|---|
| `docs/features/2026-10-03-import-agent-architecture.md` | 0 | this document |
| `backend/app/ingest/agent.py` | 1, 4 | subagent `middleware` key; parent loses research tools |
| `backend/tests/test_harness.py` | 1 | a test that inspects subagent graphs |
| `CLAUDE.md` · `docs/SKILLS.md` · `app/agent/harness.py` | 1 | correct the "nothing that writes" claim |
| `backend/app/ingest/expectations.py` | 2, 5 | the concept registry; `concepts_for(kind)` |
| `backend/app/ingest/research_records.py` | 2, 5 | derive lists; four org models; required kind |
| `backend/app/ingest/promote.py` | 2, 5 | derive `PROMOTABLE`/`NOT_WRITTEN`; org excuses |
| `backend/app/ingest/brief.py` | 2, 5 | derive titles; `rfp` branch; org headlines |
| `frontend/features/ingest/*` | 3 | failures-only strip, `humanizeTool`, kind chips, badge |
| `backend/app/ingest/instructions.md` | 4, 5 | supervisor-only; tool count; NGO branch |
| `backend/app/ingest/prompts/entity_researcher.md` | 4, 5 | access rules, tiers; resolve→classify→goals |
| `backend/app/ingest/tools/catalog_tools.py` | 5 | required kind; kind-aware `_held_per_concept` |
| `backend/app/ingest/render_docs.py` | 5 | `== "funder"`, after checking unknown rows |
| `backend/app/ingest/skills/ngo-brief-for-funders/SKILL.md` | 6 | new |
| `docs/INGEST.md` | 2 | stale gap list and concept count |
