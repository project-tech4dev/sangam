# Skills: procedures the agent loads, constraints it always carries

A skill is a directory with one file:

```
backend/app/ingest/skills/
├── research/                    the entity-researcher's, and only its
│   ├── funder-intake-research/  what to pull for a funder
│   └── ngo-credential-research/ what to pull for an NGO
├── entity-record/               the record we keep for one organisation
├── catalog-mapping/             onto the catalog, against what we hold
├── catalog-write-report/        what actually landed
├── funder-scan-for-fundraisers/ the comparison across several funders
└── ngo-brief-for-funders/       the comparison across several NGOs
    └── SKILL.md
```

Seven, in three groups, and the grouping is the point: **what to pull**,
**what to produce**, and **what the catalog did with it**. They are separate
skills rather than one long one because a run loads at most two of them —
a funder scan never needs the NGO credential chain, and neither needs the
write report until something has been written.

Two of the three groups split by entity kind, and only where the kinds
genuinely differ. A funder is researched for its intake route and its
disqualifiers; an NGO for a statutory chain — 12A, 80G, CSR-1 — that exists
on no funder table and decides whether a funder may give at all. The middle
group does not split: one organisation's record, one mapping onto the
catalog, one report, either kind.

Both "what to pull" skills name the sources card (`choose_sources`, which the person answers)
and `read_source_rows`, the researcher's reader for the staff workbooks, and the funder skill carries the per-sheet layout and unit notes the tool does not
apply. The researcher's own prompt carries the same notes, since those cannot be optional. Neither
skill names a funder, a CSO or a file.

Ask Sangam has three of its own, under `backend/app/agent/skills/`, with the
same mechanism (`app/agent/build.py`): `funder-matching` (how to get from an
organisation to verdicts), `funder-comparison` (named funders) and
`funder-shortlist-brief` (the write-up). The judging is `compare_fit`'s, in
code (`app/matching/rules.py`), so none of the three holds a matching rule.

```markdown
---
name: funder-intake-research
description: Use when someone names one or more companies, corporate
  foundations, trusts or grantmakers and wants to know what it would actually
  take to reach their money…
---

# What we want pulled for a funder
…the ten fields, in intake order…
```

The frontmatter is the advertisement, always in the prompt. The body is the
procedure, read only when the model decides the description matches. A
fundraiser types two funder names; the sixty-line brief comes from the file.

## What is a skill and what is not

**Procedures become skills. Constraints stay in the prompt.**

Progressive disclosure means the model *chooses* whether to load. That is the
whole benefit and the whole hazard. Three rules in this codebase exist because
their absence cost something real: amounts carry their unit (the crore bug
shipped twice), confirm the entity before spending budget (a run researched
Khanij Bidesh India Limited instead of the KABIL that was asked for), and a
HELD source is a dead end. None of those can sit behind a decision.

So `instructions.md` keeps identity, access rules, the evidence floor, money,
fiscal years and the tool list. A skill may add detail to those; it may never
be the only place one appears. A test holds that for tools:
`test_a_tool_is_never_reachable_only_through_a_skill`.

## Where they live, and why in the repo

`backend/app/ingest/skills/`, checked in and reviewed as a diff, for the same
reason the 74-source registry is JSON inside the package:

- it is inside the `./backend/app → /srv/app` mount, so an edit appears in the
  running container with no rebuild;
- the image does `COPY app/ app/`, which is recursive, so it ships with no
  Dockerfile change;
- and hatchling includes everything under the package, so no packaging stanza.

Kept separate from `.agents/skills/`, which is Claude Code's. Same file
format, different consumer — mixing them would have Sangam Import advertising
`langsmith-evaluator` to itself.

## How the agent reaches them

There is **no dedicated tool for loading a skill**. The model reads a SKILL.md
with the ordinary `read_file`, and `read_file` talks to whatever backend the
agent has. Both agents default to `StateBackend` — virtual files in graph
state — which is why the container cannot write `docs/`, and why a SKILL.md on
disk would otherwise be invisible.

Sangam Import therefore runs a `CompositeBackend`:

```
/skills/         → FilesystemBackend(root_dir=app/ingest/skills)   real disk
everything else  → StateBackend                                    virtual, as before
```

The path survives the round trip, which is the part worth knowing:
`ls("/skills/")` strips the route prefix, the routed backend lists its own
root, and `_remap_file_info_path` prepends `/skills/` back onto every entry
(`backends/composite.py:319-328`). So the path printed into the prompt is the
path `read_file` resolves. `test_the_route_round_trips` holds it.

**Nothing that writes exists on either agent, or on their subagents.**
`write_file`, `edit_file`, `delete` and `execute` are gone — see
`app/agent/harness.py` — so an agent cannot rewrite its own instructions
regardless of backend. `read_file` stays because `FilesystemMiddleware`
refuses to be constructed without it.

That sentence was false for the subagents until 2026-10-03, and the `/skills/`
route is exactly what made it matter. A subagent's middleware is built from
scratch (`graph.py:689-702`) with an unrestricted `FilesystemMiddleware`, and
the parent's is folded in only for `mode="fork"` — so `entity-researcher`, the
agent that reads untrusted web pages, ran `write_file` and `delete` against
the one route backed by real disk, and could have rewritten the SKILL.md every
later thread is told about. `execute` was inert throughout: `StateBackend` is
not a sandbox. The fix is one `middleware` key per spec, and
`TestASubagentRunsOnlyTheToolsItsSpecDeclares` reads the compiled subagent
graphs rather than the parent's, which is why the original tests missed it.

## Discovery, exactly

- **One level deep.** `ls` the source, then look for `<dir>/SKILL.md`. A
  nested skill is never found, and neither is a SKILL.md at the source root.
- **`name` must equal the directory name**, and `description` is capped at
  1024 characters — longer is truncated in the prompt.
- **`version` and `tags` are not read.** Any unrecognised key is ignored
  silently.
- **A malformed file is skipped with a log line, never an error.** A skill
  that quietly disappears is the failure mode to watch for, which is why
  `test_every_skill_is_one_directory_deep_with_matching_frontmatter` parses
  every one at test time.
- **Loaded once per thread.** Editing a SKILL.md mid-conversation does not
  change the advertised description until a new thread; the body, read through
  `read_file`, is always current.

## The pull skills are the researcher's; the rest are the supervisor's

An isolated subagent inherits **nothing** from the parent
(`graph.py:701-703`), so a subagent that wants skills names its own source.
`entity-researcher` declares `skills=["/skills/research/"]`, which holds only
the two pull skills. The supervisor's source is `/skills/`, and its listing
skips `research/` because that folder has no `SKILL.md` of its own.

The pull skills are a contract, not a suggestion: every field of the brief,
with the concept and field it is saved as, and each must end as a finding or
a gap. `research_goals` still names what the catalog holds; the skill names
everything the brief shows, including fields with no column yet (`unplaced`).
Because loading a skill is the model's choice, the prompt's STEP 2 tells the
researcher to read its kind's file, and `save_research` enforces the result in
code (`app/ingest/contract.py`): a save with a field that has neither a finding
nor a gap is refused, naming it. Example: an Axis save with no `rfp` finding
and no `rfp` gap comes back "rfp: no finding and no gap".
`test_only_the_researcher_declares_skills_and_only_the_pull_ones` pins it.

"Nothing" also includes the **filesystem middleware**, which is less obvious
because the library supplies an unrestricted one rather than none. Each spec
therefore carries its own `middleware=[filesystem_tools(backend)]`, which is
`keep=("read_file",)` — the floor `FilesystemMiddleware` refuses to be built
below, and not a capability either subagent uses. Neither gets `ls`: the researcher
reads its skill by the path the listing prints, so `ls` would only point at the
one backend route that is real disk.

## The cost, honestly

deepagents injects a fixed block of roughly forty lines — "Skills System", how
progressive disclosure works, an example workflow — into **every** request,
plus one index entry per skill. Seven index entries is seven lines; the
bodies — sixty to a hundred lines each — are read only when the description
matches, and a run loads at most two. That is the trade the split is making,
and it only holds while the descriptions stay disjoint enough that the model
is not loading two to find out which it needed. Splitting `instructions.md`
into six small skills would not pass the same test: the boilerplate would
cost more than the bodies saved, and those rules have to hold on every run.

That is the rule of thumb. A skill should be big enough to be worth a round
trip, and it should not load on a turn that did not need it. Both are
checkable: ask something unrelated and confirm no `read_file` appears in the
trace.

## Writing a description

It is the only thing the model sees before deciding. Write *when to use this*,
not *what this is*, and say what it is **not** for — the funder-scan
description ends by pointing single-fact questions at `funder_dossier`
instead.
