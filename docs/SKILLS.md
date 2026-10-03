# Skills: procedures the agent loads, constraints it always carries

A skill is a directory with one file:

```
backend/app/ingest/skills/
└── funder-scan-for-fundraisers/
    └── SKILL.md
```

```markdown
---
name: funder-scan-for-fundraisers
description: Use when someone names one or more companies or foundations and
  wants to know whether their NGO could get funded — CSR spend, grant sizes,
  how to apply, deadlines…
---

# A funding profile an NGO can act on
…the 28-field brief…
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

## Subagents declare their own

An isolated subagent inherits **nothing** from the parent
(`graph.py:701-703`), so `entity-researcher` names `skills=["/skills/"]`
itself. A `mode="fork"` subagent is the opposite: it inherits the parent's and
may not declare any.

"Nothing" includes the **filesystem middleware**, which is less obvious
because the library supplies an unrestricted one rather than none. Each spec
therefore carries its own `middleware=[filesystem_tools(backend, keep=…)]`:
`read_file` and `ls` for the researcher, which loads skills, and `read_file`
alone for `catalog-writer`, which loads none and takes the floor.

## The cost, honestly

deepagents injects a fixed block of roughly forty lines — "Skills System", how
progressive disclosure works, an example workflow — into **every** request,
plus one index entry per skill. For one brief-sized procedure that is a clear
win. Splitting `instructions.md` into six small skills would not be: the
boilerplate would cost more than the bodies saved, and a turn that loads two
skills is larger than one that loads none.

That is the rule of thumb. A skill should be big enough to be worth a round
trip, and it should not load on a turn that did not need it. Both are
checkable: ask something unrelated and confirm no `read_file` appears in the
trace.

## Writing a description

It is the only thing the model sees before deciding. Write *when to use this*,
not *what this is*, and say what it is **not** for — the funder-scan
description ends by pointing single-fact questions at `funder_dossier`
instead.
