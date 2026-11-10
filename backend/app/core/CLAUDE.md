# Platform

Facts: `openwiki/architecture/platform.md` (settings, lifespan, tracing) and `openwiki/architecture/auth-roles-rls.md`. Rules and decisions: `docs/ARCHITECTURE.md` §8, §10, §11.
Agents are built on the first chat turn (`load_agents()`), so no REST module may import agent code at the top.
