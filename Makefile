.PHONY: help up down logs wiki wiki-update wiki-fix wiki-deploy seed locations-seed taxonomy-seed graph-seed match calls-pull news-pull news-visibility news-seed smoke client-docs staff-source db-clean db-reset db-backup db-upgrade \
        db-init-remote db-push-remote migrate migrate-status psql db-url \
        dev-backend dev-frontend frontend-reinstall evals

SHELL := /bin/bash

# Bare `make` used to run `up`, which builds and starts four containers for
# someone who typed it to see what exists. The `##` comments below are the
# source for `make help`; keep them to one line.
.DEFAULT_GOAL := help

help:
	@awk 'BEGIN { FS = ":.*##" } \
	     /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next } \
	     /^[a-zA-Z0-9_-]+:.*##/ { printf "  \033[36m%-19s\033[0m%s\n", $$1, $$2 }' \
	     $(MAKEFILE_LIST)
	@echo
	@echo "  ENV=staging points at the managed database. It is honoured by up,"
	@echo "  down, logs, seed, migrate, psql, client-docs and the remote targets"
	@echo "  — NOT by the db-clean/reset/backup/upgrade group, which are local-only."
	@echo
	@echo "  'make up ENV=staging' runs YOUR containers against the SHARED data."
	@echo

# --- Environment selection ---------------------------------------------------
# ENV=local (default) → the bundled Postgres container.
# ENV=staging         → the STAGING_DB_* block in .env, via the staging overlay.
#
# Docker is local tooling only. ENV=staging does not deploy anything; it points
# migrations/seeding/psql at the managed database from your machine. The staging
# frontend and the backend both run on Vercel, each configured there.
ENV ?= local

ifeq ($(ENV),staging)
COMPOSE := docker compose -f docker-compose.yml -f docker-compose.staging.yml
else ifeq ($(ENV),local)
COMPOSE := docker compose
else
$(error ENV must be 'local' or 'staging', got '$(ENV)')
endif

# The effective connection string, resolved by compose itself so there is one
# source of truth. Lazy (=) so it only runs for the targets that use it, and
# routed through a script so compose's own ":? set STAGING_DB_HOST" message
# reaches the terminal instead of a parser traceback.
DB_URL = $(shell bash scripts/db-url.sh $(COMPOSE))

# A psql/pg_restore client on the compose network, so it can reach both the
# bundled container (host=postgres) and any public host.
PG_CLIENT = $(COMPOSE) run --rm --no-deps --entrypoint

# Guard for the targets that only make sense against the bundled container.
define require_local
	@test "$(ENV)" = "local" || { \
	  echo "$@ is local-only: it shells into the bundled Postgres container."; \
	  echo "For $(ENV), use 'make migrate ENV=$(ENV)' and your provider's snapshots."; \
	  exit 1; }
endef

# := so the timestamp is evaluated once per make invocation (a lazy ?= would
# re-run `date` on every reference and split the backup across directories).
# Command-line override still works: make db-upgrade BACKUP_DIR=...
BACKUP_DIR := db/backups/$(shell date +%Y%m%d-%H%M%S)

##@ Run the stack
# Three steps, not one, because the backend cannot boot against an unmigrated
# database: `_verify_sql_catalog` raises when a catalogued table is missing, and
# 12 of the catalog's 40 tables arrive in db/migrations rather than in the
# db/init baseline. So postgres comes up first, migrations run, and only then
# does the backend start. Before this, a clean checkout failed at `make up`.
#
# --wait: the frontend installs deps at container start, so without it `make up`
# would return before the first (or post-dep-change) install lands.
#
# ENV picks the database the backend RUNS against, not just the one the tooling
# targets: `make up ENV=staging` points the local stack at the managed Postgres.
# It still deploys nothing — the containers are yours, only the data is shared.
#
# Which is why the bootstrap step is local-only, and skipped when the bundled
# Postgres is switched off (COMPOSE_PROFILES without localdb). Under either,
# DATABASE_URL names somebody's managed database, and migrating it is their
# decision rather than a side effect of `make up`.
up:  ## Build and start postgres, neo4j, backend, frontend
	@if [ "$(ENV)" = "local" ] && docker compose config --services | grep -qx postgres; then \
	  docker compose up -d --wait postgres && $(MAKE) migrate ENV=local; \
	else \
	  echo "not migrating $(ENV); run migrations yourself if the backend fails to boot"; \
	fi
	$(COMPOSE) up --build -d --wait

down:  ## Stop the stack, keeping the volumes
	$(COMPOSE) down

logs:  ## Follow every container's logs
	$(COMPOSE) logs -f

# Force a frontend dependency install; the entrypoint otherwise skips it when
# package.json and package-lock.json are unchanged.
frontend-reinstall:  ## Force a frontend npm ci (make up installs only on a dep change)
	docker compose exec frontend rm -f /app/node_modules/.deps-stamp
	docker compose restart frontend

##@ Data
# `run` rather than `exec` so ENV=staging is honoured (exec would reuse the
# running container's environment, which always points at the local database).
#
# Locally this depends on `migrate` (see the conditional below): seed.taxonomy_seed
# writes tags.code and kind='csr_sector', both of which 0002_taxonomy.sql adds, so
# seeding a baseline-only database used to die on `column "code" ... does not exist`.
seed:  ## Load the cohort data (runs migrate first, locally)
	$(COMPOSE) run --rm --no-deps backend python -m seed.seed
	$(COMPOSE) run --rm --no-deps backend python -m seed.taxonomy_seed

# Local only, and deliberately so. Against a managed database `make migrate` has
# to stay an explicit, separate decision — a staging instance can be many
# migrations behind, and that is a back-it-up-first operation, not a side effect
# of seeding.
ifeq ($(ENV),local)
seed: migrate
endif

# Every Indian state and district from the LGD files in seed/data/geography. Idempotent; `make seed` already runs it.
locations-seed:  ## Load just the LGD states and districts (make seed already does)
	$(COMPOSE) run --rm --no-deps backend python -m seed.locations_seed

# Schedule VII and the theme taxonomy (tags + tag_links). Idempotent; `make seed` already runs it.
taxonomy-seed:  ## Load just the taxonomy (make seed already does)
	$(COMPOSE) run --rm --no-deps backend python -m seed.taxonomy_seed

# Build the Neo4j knowledge graph from Postgres (needs OPENAI_API_KEY in .env).
graph-seed:  ## Build the Neo4j graph from Postgres (needs OPENAI_API_KEY)
	$(COMPOSE) run --rm --no-deps backend python -m seed.graph_seed

match:  ## Save a Funder Match run for every org, or ORG=<slug>
	$(COMPOSE) run --rm --no-deps backend python -m app.matching.run $(if $(ORG),--org $(ORG))

calls-pull:  ## Read FUNDER=<slug>'s calls page, or every funder's with CONFIRM=1, and write the open calls
	$(COMPOSE) run --rm --no-deps backend python -m app.ingest.calls.run $(if $(FUNDER),--funder $(FUNDER)) $(if $(CONFIRM),--yes)

news-pull:  ## Pull news for ORG=<slug> / FUNDER=<slug>, or everyone with CONFIRM=1 (prints the plan first)
	$(COMPOSE) run --rm --no-deps backend python -m app.ingest.news.run $(if $(ORG),--org $(ORG)) $(if $(FUNDER),--funder $(FUNDER)) $(if $(CONFIRM),--yes)

news-visibility:  ## Rewrite who sees each story from the stored scores, after a bar or rule changes
	$(COMPOSE) run --rm --no-deps backend python -m app.ingest.news.run --visibility

# Stories from the pulls in seed/data/news.json, matched to this database's orgs and funders by slug. Idempotent.
news-seed:  ## Load the saved news pulls, skipping orgs and funders this database lacks
	$(COMPOSE) run --rm --no-deps backend python -m seed.news_seed

##@ Schema
# db/init/02_schema.sql is the baseline for a new database; db/migrations/*.sql
# carries every change after it. See db/migrations/README.md.
# Works against any ENV: make migrate ENV=staging
migrate:  ## Apply db/migrations/*.sql
	$(COMPOSE) run --rm --no-deps backend python -m app.db.migrate

migrate-status:  ## Show which migrations would run
	$(COMPOSE) run --rm --no-deps backend python -m app.db.migrate --status

##@ Check it works
# End-to-end smoke test of the running stack (backend, frontend, chat wire).
# SMOKE_SKIP_LLM=1 make smoke  → skips the one real agent call.
smoke:  ## End-to-end check of backend, frontend and the chat wire
	bash scripts/smoke.sh

# Golden-question evals through the real agent. Real model calls: ~10c/case.
#   make evals             every case
#   make evals TAG=canary  the cheap subset
#
# Runs on the HOST venv, not in the container: the image installs only the
# runtime dependencies from pyproject.toml, so it has no pytest. The recipe is
# @-prefixed and sources .env quietly — it carries the provider API key, and an
# echoed recipe line would put it in the terminal scrollback.
evals:  ## Golden-question evals through the real agent (COSTS MONEY)
	@set -a; [ -f .env ] && . ./.env; set +a; \
	cd backend && TEST_DATABASE_URL="postgresql://sangam:sangam@localhost:5433/sangam" \
	.venv/bin/python -m pytest tests/evals --run-evals $(if $(TAG),--eval-tag $(TAG),) -q

##@ Wiki
# openwiki/ is a generated code wiki (OpenWiki): every claim is pinned to the source lines it came from,
# and --update rewrites only pages whose evidence changed. Edit openwiki/INSTRUCTIONS.md, never a page.
# Provider is set explicitly: with it unset, OpenWiki picks OPENAI_API_KEY (the graph's key) first.
OPENWIKI = OPENWIKI_PROVIDER=anthropic OPENWIKI_MODEL_ID=claude-sonnet-5-5 OPENWIKI_TELEMETRY_DISABLED=1 \
	OPENWIKI_PAGE_CONCURRENCY=2 npx -y openwiki@0.7.2 code

wiki:  ## Generate openwiki/ from scratch (COSTS MONEY; Sonnet reads the repo)
	@set -a; [ -f .env ] && . ./.env; set +a; $(OPENWIKI) --init --print; rm -f openwiki/.run.json

wiki-update:  ## Refresh openwiki/ pages whose source changed (no model call when nothing did)
	@set -a; [ -f .env ] && . ./.env; set +a; $(OPENWIKI) --update --print; rm -f openwiki/.run.json

# --update reacts to code changes only; an INSTRUCTIONS.md edit alone rewrites nothing. A wrong page
# is fixed by asking OpenWiki's agent, so the page and its claims are edited by the same tool.
wiki-fix:  ## Ask OpenWiki to correct pages: make wiki-fix MSG="what is wrong, and where"
	@test -n "$(MSG)" || { echo 'usage: make wiki-fix MSG="..."'; exit 2; }
	@set -a; [ -f .env ] && . ./.env; set +a; $(OPENWIKI) --print "$(MSG)"; rm -f openwiki/.run.json

# The site is OpenWiki's static graph and reader; the directory name becomes the Vercel project name.
wiki-deploy:  ## Publish openwiki/ to the Vercel project sangam-wiki (needs `npx vercel login` once)
	@D="$$(mktemp -d)/sangam-wiki"; \
	OPENWIKI_TELEMETRY_DISABLED=1 npx -y openwiki@0.7.2 visualize openwiki --export "$$D" && \
	npx -y vercel@latest deploy "$$D" --prod --yes --scope team-t4d-projects

##@ Generated docs
# Render docs/entities and the generated blocks of docs/clients from the
# research table. Host venv, like `make evals`: the backend image mounts only
# app/, seed/ and db/, so nothing inside it can write a repo file.
#
# Honours ENV, but cannot use $(DB_URL) for the local case: that resolves to
# host=postgres, which only exists on the compose network, and this runs on the
# host. Local gets the published port instead; staging is a real host either way.
client-docs:  ## Render docs/entities from the research table (host venv)
	@set -a; [ -f .env ] && . ./.env; set +a; \
	cd backend && DATABASE_URL="$(if $(filter staging,$(ENV)),$(DB_URL),postgresql://sangam:sangam@localhost:5433/sangam)" \
	.venv/bin/python -m app.ingest.render_docs

# Upload one staff-only workbook (spec §4). Host venv: the file is on this machine. Staging only:
# Storage is global, so a local row would name a cloud object.
staff-source:  ## Upload a staff workbook: make staff-source ENV=staging FILE="<xlsx>" KEY=<registry key>
	@test "$(ENV)" = staging || { echo 'staff-source runs with ENV=staging only (Storage is global).'; exit 2; }
	@test -n "$(FILE)" && test -n "$(KEY)" || { echo 'usage: make staff-source ENV=staging FILE="<xlsx>" KEY=<key>'; exit 2; }
	@test -n "$(DB_URL)" || { echo 'staff-source: could not resolve the staging database URL (see scripts/db-url.sh).'; exit 2; }
	@set -a; [ -f .env ] && . ./.env; set +a; \
	STAFF_SOURCE_ENV=staging DATABASE_URL="$(DB_URL)" PYTHONPATH=backend backend/.venv/bin/python scripts/upload_staff_source.py \
	  "$(FILE)" --source-key "$(KEY)"

##@ Managed database (ENV=staging)
# Print the resolved connection string (password included — do not paste it
# into a ticket). Useful for confirming which database a target would hit.
db-url:  ## Print the resolved connection string (contains the password)
	@echo "$(DB_URL)"

# Apply db/init/*.sql to a managed Postgres. The init scripts only auto-run
# inside the bundled container, so a managed instance needs this once.
#
# RUN ONCE, against an empty database: 02_schema.sql uses bare CREATE TABLE
# (42 of them, no IF NOT EXISTS), so re-running aborts on the first existing
# object. It is not destructive — there is no DROP or TRUNCATE anywhere in
# db/init — it simply stops. The pre-flight check gives that a readable message.
db-init-remote:  ## Apply db/init/*.sql to a managed Postgres. RUN ONCE, empty DB
	@test "$(ENV)" != "local" || { echo "Refusing to run against the local database. Use: make db-init-remote ENV=staging"; exit 1; }
	@if $(PG_CLIENT) psql postgres "$(DB_URL)" -Atc "SELECT to_regclass('public.orgs') IS NOT NULL" | grep -q t; then \
	  echo "Schema already present on this database — nothing to do."; \
	  echo "(To rebuild it, drop the existing objects first; this target never drops anything.)"; \
	  exit 1; \
	fi
	$(PG_CLIENT) psql postgres "$(DB_URL)" -v ON_ERROR_STOP=1 \
	  -f /docker-entrypoint-initdb.d/01_extensions.sql \
	  -f /docker-entrypoint-initdb.d/02_schema.sql \
	  -f /docker-entrypoint-initdb.d/03_dev_user.sql
	@echo "schema applied — now run: make seed ENV=$(ENV)"

# Copy the local database (schema AND data) into the managed one. Use this
# INSTEAD OF db-init-remote when you want to carry existing data across —
# notably the 96 documents, which `make seed` does not create. Target must be empty.
db-push-remote:  ## Copy the local database, schema AND data, to a managed one
	@test "$(ENV)" != "local" || { echo "Refusing to push onto the local database. Use: make db-push-remote ENV=staging"; exit 1; }
	@if $(PG_CLIENT) psql postgres "$(DB_URL)" -Atc "SELECT to_regclass('public.orgs') IS NOT NULL" | grep -q t; then \
	  echo "Target database already has a schema — refusing to overwrite."; exit 1; \
	fi
	mkdir -p $(BACKUP_DIR)
	docker compose exec -T postgres pg_dump -U $${LOCAL_DB_USER:-sangam} -d $${LOCAL_DB_NAME:-sangam} \
	  -Fc --no-owner --no-acl > $(BACKUP_DIR)/push.dump
	docker run --rm -v $(CURDIR)/$(BACKUP_DIR):/b pgvector/pgvector:pg17 \
	  pg_restore --no-owner --no-acl --exit-on-error -d "$(DB_URL)" /b/push.dump
	@echo "pushed to $(ENV) (dump kept at $(BACKUP_DIR)/push.dump)"

# Interactive shell against whichever database ENV selects.
psql:  ## Interactive shell against whichever database ENV selects
	$(COMPOSE) run --rm --no-deps --entrypoint psql postgres "$(DB_URL)"

##@ Local-only maintenance
# Empty every table but keep the schema and the applied-migration ledger, so a
# data run can start from nothing without re-applying migrations. Does NOT drop
# volumes; `make seed` reloads the cohort. The 96 research documents are not in
# the seed - back them up first if this database still has them.
db-clean:  ## Empty every table, keep the schema and migration ledger
	$(require_local)
	docker compose exec -T postgres psql -U sangam -d sangam -v ON_ERROR_STOP=1 \
	  < db/scripts/truncate_all.sql
	@echo "every table emptied; schema and migrations intact"

# Scorched earth: drops ALL volumes including the Neo4j graph and the
# user-loaded documents/graph_ingest_log tables. Fresh installs only.
db-reset:  ## Scorched earth: drops ALL volumes, incl. Neo4j and documents
	$(require_local)
	docker compose down -v
	$(MAKE) up
	$(MAKE) seed

# Snapshot the irreplaceable tables + a linkage projection for post-restore diffing.
db-backup:  ## Snapshot the irreplaceable tables to db/backups/
	$(require_local)
	mkdir -p $(BACKUP_DIR)
	docker compose exec -T postgres pg_dump -U sangam -d sangam -Fc > $(BACKUP_DIR)/full.dump
	docker compose exec -T postgres pg_dump -U sangam -d sangam --data-only -t documents > $(BACKUP_DIR)/documents.sql
	docker compose exec -T postgres pg_dump -U sangam -d sangam -t graph_ingest_log > $(BACKUP_DIR)/graph_ingest_log.sql
	docker compose exec -T postgres psql -U sangam -d sangam -Atc \
	  "SELECT d.id||'|'||COALESCE(o.slug,'')||'|'||COALESCE(f.slug,'') FROM documents d \
	   LEFT JOIN orgs o ON o.id=d.org_id LEFT JOIN funders f ON f.id=d.funder_id ORDER BY d.id" \
	  > $(BACKUP_DIR)/documents_linkage.txt
	curl -sf localhost:8010/api/orgs -H "Authorization: Bearer dev" > $(BACKUP_DIR)/api_orgs.json || true
	curl -sf localhost:8010/api/funders -H "Authorization: Bearer dev" > $(BACKUP_DIR)/api_funders.json || true
	@echo "backup written to $(BACKUP_DIR)"

# Preserve-and-reset schema upgrade: destroys the pgdata volume and restores the
# irreplaceable tables. Superseded by `make migrate` for ordinary schema changes
# — kept only for the volume-level rebuild case, and impossible on a managed
# instance (there is no volume to remove).
db-upgrade: db-backup  ## Volume-level schema rebuild; superseded by make migrate
	$(require_local)
	docker compose rm -sf backend postgres
	docker volume rm sangam_pgdata
	docker compose up -d --wait postgres
	$(MAKE) migrate ENV=local
	docker compose up --build -d --wait backend
	$(MAKE) seed
	docker compose exec -T postgres psql -U sangam -d sangam -v ON_ERROR_STOP=1 < $(BACKUP_DIR)/documents.sql
	docker compose exec -T postgres psql -U sangam -d sangam -v ON_ERROR_STOP=1 < $(BACKUP_DIR)/graph_ingest_log.sql
	docker compose exec -T postgres psql -U sangam -d sangam -v ON_ERROR_STOP=1 -c \
	  "SELECT setval(pg_get_serial_sequence('documents','id'), (SELECT max(id) FROM documents));"
	docker compose exec -T postgres psql -U sangam -d sangam -v ON_ERROR_STOP=1 -At \
	  < db/scripts/verify_migration.sql > $(BACKUP_DIR)/linkage_after.txt
	@diff <(grep '|' $(BACKUP_DIR)/linkage_after.txt) $(BACKUP_DIR)/documents_linkage.txt \
	  && echo "LINKAGE OK: restored documents attach to identical org/funder slugs" \
	  || (echo "LINKAGE MISMATCH — investigate before proceeding" && exit 1)

##@ Run outside Docker
dev-backend:  ## Run uvicorn on the host against the compose Postgres
	cd backend && DATABASE_URL="host=localhost port=5433 user=sangam password=sangam dbname=sangam" \
		uvicorn app.main:app --reload

dev-frontend:  ## Run next dev on the host against a host backend
	cd frontend && set -a && source <(grep -E '^NEXT_PUBLIC_SUPABASE_' ../.env) && set +a && \
		AGENT_URL=http://localhost:8000/agent npm run dev
