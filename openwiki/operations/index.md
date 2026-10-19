# Files

- [Deploy and vendors](deploy-and-vendors.md) - Operating facts for Sangam's delivery and vendors - the CI workflow, Dependency review check, Codecov and Dependabot-driven bumps (none of which deploy), versus the hand-run Deploy workflow, plus the two Vercel projects, Supabase, Tavily, Langfuse and Neo4j Aura and what each does when unconfigured or down.
- [Environments and Env Vars](environments.md) - How ENV=local and ENV=staging select a database for local Docker tooling, how the two docker-compose files and the Makefile fit together, a grouped reference of the env vars, and how blank values and defaults resolve in Settings.
