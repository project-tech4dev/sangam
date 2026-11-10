# Files

- [Testing](overview.md) - How the backend test suite is split into unit tests (no database), integration tests (compose Postgres on :5433) and evals (real model calls that cost money), how to run each tier, how the CI workflow, dependency review and Codecov check every PR (CI never deploys), and which tests pin the system's security, tool-surface and proposal-copilot invariants.
