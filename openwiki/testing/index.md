# Files

- [Testing](overview.md) - How the backend test suite is split into unit tests (no database), integration tests (compose Postgres on :5433) and evals (real model calls that cost money), how the frontend Vitest suite runs, how the CI workflow, dependency review and per-component Codecov 75% gates check every PR (CI never deploys), the test_cov_* coverage push, and which tests pin the system's security, tool-surface and proposal-copilot invariants.
