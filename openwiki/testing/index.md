# Files

- [Testing](overview.md) - How the backend test suite is split into unit tests (no database), integration tests (compose Postgres on :5433) and evals (real model calls that cost money), how the frontend Vitest suite and the per-component Codecov thresholds work, how CI and dependency review check every PR (CI never deploys), and which tests pin the system's architecture, security, tool-surface and proposal-copilot invariants.
