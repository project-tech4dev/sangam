.PHONY: up down logs seed taxonomy-seed graph-seed smoke client-docs db-clean db-reset db-backup db-upgrade \
        db-init-remote db-push-remote migrate migrate-status psql db-url \
        dev-backend dev-frontend frontend-reinstall evals

SHELL := /bin/bash

# --- Environment selection ---------------------------------------------------
# ENV=local (default) → the bundled Postgres container.
# ENV=staging         → the STAGING_DB_* block in .env, via the staging overlay.
#
# Docker is local tooling only. ENV=staging does not deploy anything; it points
# migrations/seeding/psql at the managed database from your machine. The staging
# frontend runs on Vercel and the backend on its own host, each configured there.
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

# --- Stack -------------------------------------------------------------------
up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

# Force a frontend dependency install; the entrypoint otherwise skips it when
# package.json and package-lock.json are unchanged.
frontend-reinstall:
	docker compose exec frontend rm -f /app/node_modules/.deps-stamp
	docker compose restart frontend

# `run` rather than `exec` so ENV=staging is honoured (exec would reuse the
# running container's environment, which always points at the local database).
seed:
	$(COMPOSE) run --rm --no-deps backend python -m seed.seed
	$(COMPOSE) run --rm --no-deps backend python -m seed.taxonomy_seed

# Schedule VII on its own. Idempotent; `make seed` already runs it.
taxonomy-seed:
	$(COMPOSE) run --rm --no-deps backend python -m seed.taxonomy_seed

# Build the Neo4j knowledge graph from Postgres (needs OPENAI_API_KEY in .env).
graph-seed:
	$(COMPOSE) run --rm --no-deps backend python -m seed.graph_seed

# End-to-end smoke test of the running stack (backend, frontend, chat wire).
# SMOKE_SKIP_LLM=1 make smoke  → skips the one real agent call.
smoke:
	bash scripts/smoke.sh

# --- Schema ------------------------------------------------------------------
# db/init/02_schema.sql is the baseline for a new database; db/migrations/*.sql
# carries every change after it. See db/migrations/README.md.
# Works against any ENV: make migrate ENV=staging
migrate:
	$(COMPOSE) run --rm --no-deps backend python -m app.db.migrate

# Golden-question evals through the real agent. Real model calls: ~10c/case.
#   make evals             every case
#   make evals TAG=canary  the cheap subset
#
# Runs on the HOST venv, not in the container: the image installs only the
# runtime dependencies from pyproject.toml, so it has no pytest. The recipe is
# @-prefixed and sources .env quietly — it carries the provider API key, and an
# echoed recipe line would put it in the terminal scrollback.
evals:
	@set -a; [ -f .env ] && . ./.env; set +a; \
	cd backend && TEST_DATABASE_URL="postgresql://sangam:sangam@localhost:5433/sangam" \
	.venv/bin/python -m pytest tests/evals --run-evals $(if $(TAG),--eval-tag $(TAG),) -q

# Render docs/entities and the generated blocks of docs/clients from the
# research table. Host venv, like `make evals`: the backend image mounts only
# app/, seed/ and db/, so nothing inside it can write a repo file.
client-docs:
	@set -a; [ -f .env ] && . ./.env; set +a; \
	cd backend && DATABASE_URL="postgresql://sangam:sangam@localhost:5433/sangam" \
	.venv/bin/python -m app.ingest.render_docs

migrate-status:
	$(COMPOSE) run --rm --no-deps backend python -m app.db.migrate --status

# Print the resolved connection string (password included — do not paste it
# into a ticket). Useful for confirming which database a target would hit.
db-url:
	@echo "$(DB_URL)"

# Apply db/init/*.sql to a managed Postgres. The init scripts only auto-run
# inside the bundled container, so a managed instance needs this once.
#
# RUN ONCE, against an empty database: 02_schema.sql uses bare CREATE TABLE
# (42 of them, no IF NOT EXISTS), so re-running aborts on the first existing
# object. It is not destructive — there is no DROP or TRUNCATE anywhere in
# db/init — it simply stops. The pre-flight check gives that a readable message.
db-init-remote:
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
db-push-remote:
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
psql:
	$(COMPOSE) run --rm --no-deps --entrypoint psql postgres "$(DB_URL)"

# --- Local-only maintenance --------------------------------------------------
# Empty every table but keep the schema and the applied-migration ledger, so a
# data run can start from nothing without re-applying migrations. Does NOT drop
# volumes; `make seed` reloads the cohort. The 96 research documents are not in
# the seed - back them up first if this database still has them.
db-clean:
	$(require_local)
	docker compose exec -T postgres psql -U sangam -d sangam -v ON_ERROR_STOP=1 \
	  < db/scripts/truncate_all.sql
	@echo "every table emptied; schema and migrations intact"

# Scorched earth: drops ALL volumes including the Neo4j graph and the
# user-loaded documents/graph_ingest_log tables. Fresh installs only.
db-reset:
	$(require_local)
	docker compose down -v
	docker compose up --build -d
	@echo "waiting for backend to be healthy..." && sleep 5
	$(MAKE) seed

# Snapshot the irreplaceable tables + a linkage projection for post-restore diffing.
db-backup:
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
db-upgrade: db-backup
	$(require_local)
	docker compose rm -sf backend postgres
	docker volume rm sangam_pgdata
	docker compose up --build -d backend
	@echo "waiting for backend (initdb + checkpointer setup)..." && sleep 10
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

# --- Dev outside docker ------------------------------------------------------
dev-backend:
	cd backend && DATABASE_URL="host=localhost port=5433 user=sangam password=sangam dbname=sangam" \
		uvicorn app.main:app --reload

dev-frontend:
	cd frontend && set -a && source <(grep -E '^NEXT_PUBLIC_SUPABASE_' ../.env) && set +a && \
		AGENT_URL=http://localhost:8000/agent npm run dev
