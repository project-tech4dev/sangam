---
paths:
  - "backend/app/core/**"
  - "backend/app/integrations/**"
  - "backend/app/main.py"
  - "backend/vercel.json"
  - "frontend/vercel.json"
  - ".github/workflows/**"
  - "docker-compose*.yml"
  - "Makefile"
---

# Platform

Before changing this code, read `docs/ARCHITECTURE.md` §8, §10 and §11. They cover auth and the two pools, model tiers and settings, deploy, tracing and the keep-warm cron.
Agents are built on the first chat turn (`load_agents()`), so no REST module may import agent code at the top.
