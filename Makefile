.PHONY: up down logs seed graph-seed db-reset db-backup db-upgrade psql dev-backend dev-frontend

SHELL := /bin/bash

# := so the timestamp is evaluated once per make invocation (a lazy ?= would
# re-run `date` on every reference and split the backup across directories).
# Command-line override still works: make db-upgrade BACKUP_DIR=...
BACKUP_DIR := db/backups/$(shell date +%Y%m%d-%H%M%S)

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

seed:
	docker compose exec backend python -m seed.seed

# Build the FalkorDB knowledge graph from Postgres (needs OPENAI_API_KEY in .env).
graph-seed:
	docker compose exec backend python -m seed.graph_seed

# Scorched earth: drops ALL volumes including FalkorDB graph data and the
# user-loaded documents/graph_ingest_log tables. For fresh installs only —
# for schema upgrades that preserve data, use `make db-upgrade`.
db-reset:
	docker compose down -v
	docker compose up --build -d
	@echo "waiting for backend to be healthy..." && sleep 5
	$(MAKE) seed

# Snapshot the irreplaceable tables + a linkage projection for post-restore diffing.
db-backup:
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

# Preserve-and-reset schema upgrade: keeps documents + graph_ingest_log (and the
# FalkorDB graph volume — deliberately NEVER uses `docker compose down -v`).
# Chat checkpoints are dropped (recreated by the checkpointer at boot).
db-upgrade: db-backup
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

# End-to-end smoke test of the running stack (backend, frontend, chat wire).
# SMOKE_SKIP_LLM=1 make smoke  → skips the one real agent call.
smoke:
	bash scripts/smoke.sh

psql:
	docker compose exec postgres psql -U sangam -d sangam

# Dev outside docker (postgres still from compose; ports 5432/8000 published):
dev-backend:
	cd backend && DATABASE_URL=postgresql://sangam:sangam@localhost:5433/sangam \
		uvicorn app.main:app --reload

dev-frontend:
	cd frontend && AGENT_URL=http://localhost:8000/agent npm run dev
