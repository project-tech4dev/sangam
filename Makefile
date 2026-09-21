.PHONY: up down logs seed db-reset psql dev-backend dev-frontend

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

# Drop the DB volume and recreate everything (schema re-runs from db/init/).
db-reset:
	docker compose down -v
	docker compose up --build -d
	@echo "waiting for backend to be healthy..." && sleep 5
	$(MAKE) seed

psql:
	docker compose exec postgres psql -U sangam -d sangam

# Dev outside docker (postgres still from compose; ports 5432/8000 published):
dev-backend:
	cd backend && DATABASE_URL=postgresql://sangam:sangam@localhost:5433/sangam \
		uvicorn app.main:app --reload

dev-frontend:
	cd frontend && AGENT_URL=http://localhost:8000/agent npm run dev
