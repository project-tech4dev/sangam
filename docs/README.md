# Docs

Start with **`ARCHITECTURE.md`**, the system as it works today. Read **`HISTORY.md`** for what was built when, and for which plans are unfinished.
The rest go deeper on one area. Read one when the task touches that area.

| Doc | What it is | Read when |
|---|---|---|
| `ARCHITECTURE.md` | Every subsystem today: files, flows, tools, tables, routes, settings | Before changing anything; read the section for your area |
| `HISTORY.md` | Everything shipped, by subsystem and PR; "Not finished" lists partial plans | Before trusting a plan doc, or to learn why something is the way it is |
| `SQL_AGENT.md` | Ask's text-to-SQL design: catalog, validator, executor, audit | Changing the SQL tools or adding a table to the catalog |
| `INGEST.md` | Import's sources and access rules, amounts, fiscal years, the writer's refusals | Changing Import's sources or writer (its header lists what is stale) |
| `SKILLS.md` | How skills are discovered, loaded and kept out of constraints | Adding or changing a skill for either agent |
| `DATA_PLATFORM.md` | The v3 data model and the reasoning behind it | Designing a schema change |
| `DESIGN_SYSTEM.md` | Link to the design system, file mapping, how to sync | Any UI change |
| `DEPLOY.md` | A container-host setup that was **never used** | Don't; ARCHITECTURE.md §11 is the live setup |
| `features/*.md` | One dated plan per feature | Planning a change in that feature; check its status in HISTORY.md |
| `entities/*.md` | Rendered research briefs (`make client-docs`) | Data, not architecture |

Agents get the right ARCHITECTURE section without asking: `.claude/rules/arch-*.md` are path-scoped and load
when an agent touches that part of the tree. `CLAUDE.md` holds the commands and the invariants every session needs.
