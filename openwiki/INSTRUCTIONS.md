---
type: Repository guide
title: Repository Wiki Instructions
description: What the Sangam code wiki must cover, where the reasoning behind the code lives, and the ground rules a page may never contradict.
tags: [documentation, repository, code-wiki]
---

Sangam is a catalog of Indian CSR funders and NGOs with two agents on one FastAPI backend.
**Ask Sangam** (`backend/app/agent/`) answers questions by writing its own SQL behind a catalog allowlist.
**Sangam Import**, shown on screen as **Sangam Scout** (`backend/app/ingest/`), researches organisations on the open web and promotes cited findings into the catalog.
Around them are:
- **Funder Match** (`backend/app/matching/`): judged in code, no model.
- **Media & Signals** (`backend/app/ingest/news/`).
- A Next.js frontend (`frontend/`).
- Postgres with RLS on Supabase, deployed on Vercel.

## Pages wanted

- `quickstart`: first run, the make targets that matter, and which page to read for which task.
- One architecture page per area:
  - Ask Sangam: tools, skills, middleware, the four SQL layers, citations.
  - Sangam Import / Scout: agents and subagents, tools, middleware, the brief, promote, writer, matcher, undo, access.
  - Funder Match.
  - Media & Signals.
  - Data and migrations: tables by group, storage buckets, provenance.
  - Auth, roles and RLS: the caller pool vs the owner pool.
  - Frontend: routes, features, workspace views, the chat wire.
  - Platform: config and model tiers, lifespan, tracing, deploy, performance.
- Workflows:
  - one Ask turn, end to end;
  - one Import turn from `choose_sources` through `save_research`, the brief, promotion and undo;
  - writing and applying a migration;
  - deploying by hand.
- Operations: environments (`ENV=local|staging`), env vars, Vercel and Supabase specifics.
- Testing: unit tests (no database), integration tests, and evals (real model calls, which cost money).

Keep pages practical for an engineer or a coding agent about to change code: file paths, the order things happen in, and what breaks if a rule is ignored.

## Where the reasoning lives

The code says *what*. These say *why*. Read them before describing a design choice:
- `CLAUDE.md`: the invariants every contributor must keep.
- `docs/ARCHITECTURE.md`: the curated summary, with known regressions.
- `docs/CHANGELOG.md`: every PR by subsystem. Its **"Not finished"** table says which plans are only partly built.
- `docs/features/*.md`: one plan per feature. A plan's own status line can be out of date; the changelog is right.
- `docs/SQL_AGENT.md`, `docs/SKILLS.md`, `docs/DATA_PLATFORM.md`, `docs/DESIGN_SYSTEM.md`.
- `docs/INGEST.md`: **partly stale** since #192–#197. Its header lists what is wrong. Trust the code.
- The git log: PR titles and bodies explain most changes.

Report an unfinished plan as unfinished, and a known regression as a regression. Link to the changelog rather than restating it.

## Ground rules a page must never contradict

- Each agent's tool list is fixed and pinned by tests: Ask has seven tools plus `read_file`/`ls`. Subagents carry their own filesystem middleware.
- Agent tools never raise; they return an error string. Every database row they return carries a citation marker.
- `backend/app/agent/tools/sql/catalog.py` is a security allowlist. Adding a table to it is a security decision.
- Migrations are not automatic (`make migrate`), and schema changes go only in `db/migrations/`.
- Nothing deploys automatically; `.github/workflows/deploy.yml` is run by hand.
- Postgres is the system of record. The Neo4j graph is optional and rebuildable.
- In Import, the published brief (`source-archive/entities/<slug>.md`) is the record that promotion reads.

## Facts that earlier pages got wrong

Check these against the code before restating them:
- **SQL catalog size.** It allowlists 37 tables, and `KNOWN_EXCLUDED` holds 22 (`backend/app/agent/tools/sql/catalog.py`). State both counts.
- **Import's subagents.** There are four: `entity-researcher`, `vault-reader`, `catalog-writer`, `workbook-reader`. In `test_harness.py`, `test_import_advertises_exactly_its_two_subagents` checks only that two are advertised and `general-purpose` is absent. `test_both_subagents_are_compiled_and_found` asserts the exact set of four.
- **Import's NGO promote path.** It resolves a parent body (`_org_parent` in `promote.py`).
- **The funder promote path's order** is: funder, then tags, then documents, then CSR years, then programmes.
- **`StaffLastLock` and `SaveQuestions`** live in `app/agent/middleware.py`, but only Import uses them; Ask does not.
- **`ReadingLimit`** applies to the entity-researcher only. The vault-reader and the catalog-writer have only `call_limit`.
- **Proposals.** A `proposals` table exists (`0009`), with grants and RLS, but no backend code reads or writes it. Proposals live in browser `localStorage`.
- **Missing Supabase keys on the frontend.** `lib/supabase/middleware.ts` passes requests through when the keys are absent. Describe the actual failure, and say it the same way on every page.
- **When the agents are built.** It happens on first use: the first post to `/agent` or `/ingest`, or a REST route calling `get_graph`.
- **Auth-skipped paths** include `/docs/oauth2-redirect`.
- **The owner pool** connects as the database owner, a superuser locally. Do not claim more about the deployed role than the code shows.

## Out of scope

Research outputs about real organisations (`docs/entities/`), seed data and anything under `.memory/` are not architecture. Never describe their contents.
