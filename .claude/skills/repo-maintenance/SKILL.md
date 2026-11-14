---
name: repo-maintenance
description: "INVOKE THIS SKILL when Sangam needs repository upkeep: syncing or merging branches, resolving merge conflicts, upgrading backend (uv) or frontend (npm) dependencies, writing a PR description, or turning a deployment requirement into vercel.json, docker-compose or GitHub Actions config. Works locally, verifies with the same checks CI runs, and asks before any push, PR or deploy. Not for feature work or schema changes."
---

<oneliner>
Do one maintenance job on Sangam, prove it with CI's own checks, and hand back a branch ready to push with its PR description.
</oneliner>

## Ground rules

| rule | example |
|---|---|
| **Work in a worktree, never in the shared checkout.** Several sessions use `~/Documents/sangam` at once. | `git worktree add -b chore/bump-langgraph ../sangam-bump-langgraph origin/master` |
| **`master` is the base**, unless the work stacks on an open PR. | A fix to PR #263 goes on `feat/pitch-public-research`, not a new branch off master. |
| **Local only until the person says so.** Merge, edit, upgrade and run checks freely; ask before `git push`, `gh pr create`, or running Deploy. | End with "Ready to push `chore/bump-langgraph` and open the PR?" |
| **Never deploy.** Merging to master deploys nothing; only Actions → Deploy → Run workflow does, by hand. | Say "Deploy is manual" in the summary; do not run the workflow. |
| **Never read `.env`.** Read `.env.example`; ask for values. | A new key goes in `.env.example` and `backend/app/core/config.py`, never filled in. |
| **Never force-push or rewrite a pushed branch** without an explicit yes. | Sync with `git merge origin/master`, not rebase, on a branch that is already pushed. |

## Steps

### 1. Inspect

- `git status`, `git log --oneline -5`, `git worktree list`: know which branch and worktree you are in.
- `gh pr list --head <branch>`: is there already a PR, and does the work stack on it?
- For a dependency job: `backend/pyproject.toml` + `backend/uv.lock`, `frontend/package.json` + `frontend/package-lock.json`.
- For a config job: `backend/vercel.json`, `frontend/vercel.json`, `docker-compose.yml`, `docker-compose.staging.yml`, `.github/workflows/{ci,deploy,dependency-review}.yml`.

State in one line what you found before changing anything.

### 2. Do the job

**Sync or merge a branch.** `git fetch origin`, then `git merge origin/master` into the branch. On a conflict:
- read both sides and the commits that made them (`git log -p --merge -- <file>`); keep both intents, never pick a side blind;
- `db/migrations/`: never renumber or edit an applied migration; a clash of numbers is resolved by the later branch taking the next free number;
- `openwiki/`: never hand-merge; take either side, then run `make wiki-update` (it costs money, so ask first);
- `docs/CHANGELOG.md`: keep every line from both sides.

**Upgrade dependencies.**
- Backend: `cd backend && uv lock --upgrade-package <pkg>` (one package at a time unless asked for all), then `uv sync`.
- Frontend: `cd frontend && npm install <pkg>@<version>`; commit `package-lock.json` with it.
- Read the package's changelog between the two versions and name any breaking change.
- `deepagents`, `langchain`, `langgraph`: the harness tests (`tests/test_harness*.py` and the reader/subagent tool tests) exist because an upgrade is free to add tools. Run them and read any failure as a security finding, not noise.
- Keep the backend under Vercel's 500 MB Python bundle limit; say if a new dependency is large.

**Turn a requirement into config.**
- **Vercel**: each `vercel.json` stays in its project's root (`frontend/`, `backend/`). Keep `"regions": ["bom1"]` and `"git": {"deploymentEnabled": false}`. `maxDuration` in `backend/vercel.json` and in `frontend/app/api/copilotkit/[[...slug]]/route.ts` must match.
- **Docker Compose**: local development only. A new service gets a healthcheck like the others; a new env var goes in `.env.example` too.
- **GitHub Actions**: `ci.yml` runs on every PR; `deploy.yml` is `workflow_dispatch` only and must stay that way. Secrets come from `secrets.*`; the org and project IDs are identifiers, not credentials.

### 3. Verify

Run what CI runs, in this order, and keep the full output of any failure:

```bash
cd backend && uv run ruff check . && uv run pytest -m "not integration" -q
cd frontend && npm run lint && npx tsc --noEmit && npm run build   # revert next-env.d.ts if build touched it
```

Then the job-specific check:

| job | extra check |
|---|---|
| merge or sync | `git diff origin/master...HEAD --stat` shows only the branch's own work; no conflict markers (`git grep -n '^<<<<<<<\|^>>>>>>>'`) |
| dependency upgrade | the lockfile changed only for the named packages; `uv tree` / `npm ls <pkg>` show the new version |
| compose change | `docker compose config -q`, then `make up && make smoke` (`SMOKE_SKIP_LLM=1` to skip the paid call) |
| Actions change | `actionlint` if installed; otherwise read the YAML against an existing job |
| vercel.json change | valid JSON; `regions` and `maxDuration` still agree with the other project |

A migration-touching merge also runs `pytest -m integration` against the compose Postgres on `:5433`.

### 4. Commit and write the PR description

One commit per logical change, conventional prefix (`chore(deps):`, `ci:`, `fix(merge):`), ending with the session's attribution lines.

PR description, short and in this shape:

```markdown
## What
One or two sentences: what changed and why now.

## Changes
- one line per change, with the file

## Checks
- backend: ruff clean; pytest N passed
- frontend: lint 0 errors; build passes
- <the job-specific check and its result>

## Not done
- [ ] anything skipped (wiki-update, integration tests, a live run), and why
```

A PR that changes a tool, table, route or flow needs `make wiki-update`; one that ships something adds a line to `docs/CHANGELOG.md`.

### 5. Hand back

Report one line per item: branch and worktree, what changed, each check with its result, what was not done. Then ask whether to push and open the PR. After a merge to master, remind the person that Deploy is run by hand.
