# Security policy

## Reporting a vulnerability

**Please do not open a public issue.** Report it privately through GitHub:
[**Report a vulnerability**](https://github.com/project-tech4dev/sangam/security/advisories/new).

Include what you found, how to reproduce it, and what an attacker could do with it. We will acknowledge
the report within five working days, keep you updated while we fix it, and credit you in the advisory
unless you would rather we didn't.

## Supported versions

Sangam is pre-release and deploys from `master`. Only the latest `master` receives fixes.

## Scope

We especially want to hear about:

- **The SQL agent's guards.** Ask Sangam writes its own SQL. Anything that gets a query past the catalog
  allowlist, the validator, the read-only transaction or the caller's row-level security
  (`docs/SQL_AGENT.md`) is in scope.
- **Access control.** Reading or writing another organisation's data, chats, Doc Vault files or Funder
  Match runs; reaching staff-only routes such as Import (Scout) without the role.
- **Prompt injection with an effect.** A page or document the agents read that makes them leak rows,
  write data, or fetch a URL they should not. Every model-supplied URL goes through
  `app/core/egress.py`.
- **Server-side request forgery** past that egress guard, and leaked secrets or keys.

Out of scope: findings that need a compromised account or machine, denial of service by volume, and
reports from automated scanners without a demonstrated impact.
