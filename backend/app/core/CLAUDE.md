# Platform

How this works today is `docs/ARCHITECTURE.md`. §8 covers auth and the two pools, §10 model tiers and settings, and §11 deploy, tracing and the keep-warm cron.
Agents are built on the first chat turn (`load_agents()`), so no REST module may import agent code at the top.
