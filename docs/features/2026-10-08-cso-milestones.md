# CSO model consolidation — milestones

Spec: `features-plans/data-model/2026-10-07-cso-model-consolidation.md` (PR #102). Its plans (d)/(e)/(f) predate
#103/#105 and are reference for intent only; locate code by symbol on this branch.

**Goal:** a full, sourced CSO profile. Every fact has a column and an evidence tier, a weaker source never
overwrites a stronger one, grant money lives only in `funder_activity`, and registry checks a machine
cannot make are recorded by staff with evidence.

Four stacked PRs: #102 ← M1 ← M2 ← M3 ← M4.

## M1 — CSO facts have a home and a trust level (`feat/cso-m1-facts-and-tiers`, migration 0033)
- `orgs` gains website, description, aliases, staff count; `org_financials` gains `foreign_unspent`.
- Registration status lives on `org_identifiers` (surrogate key, nullable value); `credential_events` dropped.
- Every CSO fact carries `source_type` + `evidence`; writes follow one precedence rule; disagreements land in `conflicts`.
- `resolve_org` matches aliases and normalised names.
- Exit: weaker never overwrites stronger; "applied" is never stored as "registered"; 0033 applies on a scratch clone.

## M2 — One place for grant money (`feat/cso-m2-grants`, migration 0034)
- Grant rows migrate into `funder_activity` partner lines; `grants`, `program_locations`, `grant_locations` dropped.
- `/api/grants` and its route/repository/schema deleted; a partner-lines read replaces it; three pages move to it.
- `[grant:N]` removed everywhere; the agent cites `[activity:N]`.
- A CSO's funders found in research become partner lines on the funder side.
- Exit: nothing mentions `grants`; CSO and funder pages show the same money as before; frontend builds.

## M3 — Registry checks and the credential skill (`feat/cso-m3-checks-skill`)
- `record_registry_check`: staff record a Darpan/FCRA/MCA check with uploaded evidence.
- `ngo-credential-research` rewritten: statuses not yes/no, audited financials, documents to request from the CSO.
- Exit: a recorded check is cited by the agent; `check_blocked` is never reported as valid.

## M4 — Aggregators and prior research (`feat/cso-m4-sources`)
- Give.do and GuideStar India readable only on named paths, values always `claimed`.
- org-grant-intelligence read first, stored as `prior_research`, cited links re-fetched.
- Exit: security sign-off on the access rules; fetches outside allowed paths are refused.

## Build method
- Each milestone in stages: a fresh implementer subagent, then a fresh reviewer, then fixes; a whole-branch review per PR.
- No new tests (team rule); existing tests a change breaks are fixed, not deleted.
- Never migrate the shared `sangam` DB; integration work runs on the scratch clone `sangam_cso`.
