# Docs

Start with **`ARCHITECTURE.md`**, the rules and decisions behind the system. For a fact about an area (a tool, route, table, setting), open its generated page in [`openwiki/`](../openwiki/quickstart.md). Read **`CHANGELOG.md`** for what was built when, and for which plans are unfinished.
The rest go deeper on one area. Read one when the task touches that area.

| Doc | What it is | Read when |
|---|---|---|
| `../openwiki/` | Generated pages per area, each claim pinned to source (`make wiki-update` keeps it current) | You need a fact about an unfamiliar area; never hand-edit |
| `ARCHITECTURE.md` | Each area's invariants, decisions and known regressions, linking its wiki page | Before changing anything; read the section for your area |
| `CHANGELOG.md` | Everything shipped, by subsystem and PR; "Not finished" lists partial plans | Before trusting a plan doc, or to learn why something is the way it is |
| `SQL_AGENT.md` | Ask's text-to-SQL design: catalog, validator, executor, audit | Changing the SQL tools or adding a table to the catalog |
| `INGEST.md` | Import's sources and access rules, amounts, fiscal years, the writer's refusals | Changing Import's sources or writer (its header lists what is stale) |
| `SKILLS.md` | How skills are discovered, loaded and kept out of constraints | Adding or changing a skill for either agent |
| `DATA_PLATFORM.md` | The v3 data model and the reasoning behind it | Designing a schema change |
| `DESIGN_SYSTEM.md` | Link to the design system, file mapping, how to sync | Any UI change |
| `features/*.md` | One dated plan per feature | Planning a change in that feature; check its status in CHANGELOG.md |
| `entities/*.md` | Rendered research briefs (`make client-docs`) | Data, not architecture |

Agents get the right ARCHITECTURE section without asking: nested `CLAUDE.md` files in `backend/app/agent/`,
`backend/app/ingest/`, `backend/app/matching/`, `backend/app/core/`, `db/` and `frontend/` load when an agent
works in that folder and point at both the wiki page and the ARCHITECTURE section. `CLAUDE.md` holds the commands and the invariants every session needs.
