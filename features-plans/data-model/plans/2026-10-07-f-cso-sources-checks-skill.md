# CSO sources, manual registry checks and the credential skill — Implementation Plan

> **For agentic workers:** REQUIRED: execute this plan with superpowers:subagent-driven-development — a fresh implementer subagent per task, a fresh reviewer subagent checking each task before the next starts, and a whole-branch review at the end. Do not use executing-plans or implement inline. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import gets four new capabilities. Each one has a rule in code, not only in a prompt.

1. **Two aggregators it may read.** Give.do's public `/discover/` pages and GuideStar India's public search API. Every value from them is `claimed`.
2. **The team's earlier research repository, read first.** This is `org-grant-intelligence`, pinned to one commit. Every value from it is `prior_research` and `claimed` until a primary source re-reads it.
3. **A staff-only tool, `record_registry_check`.** It records a registry check a person made by hand, together with the document that shows it.
4. **A rewritten, generic `ngo-credential-research` skill.** It reads sources in a set order and states statuses rather than yes/no. It also lists exactly which documents to request from the CSO.

Two more pieces round it out:
- Pages behind a CAPTCHA or a sign-in come back as `check_blocked`, never as "not found".
- The staff CSO workbook's layout profile (#99, plan (c)) holds back any funder block whose rows name the CSO itself as a funder.

**Architecture:**

- **Path-scoped access rules.** Two new `AccessRule` values, `manual_aggregator` and `internal_research`, are **path-scoped**. A registry entry under one of them names the exact paths (`allowed_paths`) and query parameters (`allowed_query`) the researcher's fetch tools may read on its host. The entry governs those paths and nothing else.
  - `rule_for_url()` resolves a URL in two steps. First it looks for a path-scoped entry that claims the path. If none does, it falls back to the strictest other rule on the host. So `give.do/discover/…` is the aggregator's, while `give.do/api/…` stays under the existing `give` entry's `no_scraping` refusal.
  - `DISPATCHABLE` is unchanged. No adapter crawls either kind.
- **One request hook per hop.** `read_page` and `fetch_document` now build their `httpx` client with a request hook. The hook runs `check_url` on every redirect hop *before* that hop is requested, so a redirect cannot carry a read off the allowlist.
  - `blocked_page()` turns a 401/403/429, a sign-in path or a CAPTCHA into a `CHECK BLOCKED:` reply.
  - JSON and plain-text responses (the GuideStar API, raw GitHub markdown) are returned as text instead of going through `trafilatura`.
  - Every aggregator or prior-research page opens with a banner that says how to label what is on it.
- **Two guards, at save and at promote.** `app/ingest/source_guards.py` is pure.
  - It refuses at save (an `EntityResearch` validator) any finding from an aggregator or from the research repository that is not labelled `claimed` with the right `source_type`.
  - It also refuses an `org_identifier` saved as `not_found` from a registry Sangam cannot read.
  - At promotion it re-checks the same rules, and holds any such finding whose target table cannot mark a value claimed.
- **Manual checks.** `app/ingest/manual_checks.py` validates and writes one manual check onto `org_identifiers`, using the columns PR (d) adds. The tool `record_registry_check` (`app/ingest/tools/registry_check_tools.py`) wraps it.
  - The tool goes on the supervisor, which is the agent the staff member is talking to. The researcher reads untrusted pages and the catalog-writer only promotes saved research, so neither gets it.
  - The checker is taken from the conversation (`chat_user_id`), never from an argument.
- **The self-named block.** A profile flag, `hold_self_named_blocks`, changes the profile digest, so plan (c)'s sidecars rebuild. `_read_blocks` marks a self-named block `held`. `staff_sources.search` renders a held block with no marker, no CSO and no row content. The upload script reports it to staff so the sheet can be fixed at source.

**Tech Stack:** Python 3.12, httpx (request event hooks, `MockTransport` in tests), pydantic v2, psycopg 3, deepagents/LangGraph, openpyxl (from plan (c)), Next.js (`toolLabels.ts`), pytest (`asyncio_mode = "auto"`).

**Spec:** features-plans/data-model/2026-10-07-cso-model-consolidation.md (§4, §4a, §5; C8–C10, C12, C14)

## Global Constraints

- **Order.** This PR lands after #99's (a), (b) and (c) and after this spec's (d) and (e). Task 1, Step 1 verifies every interface below before any code changes. If a name differs, **stop and report**. Do not guess, and do not re-implement what (c), (d) or (e) own.

  | Taken from | Interface this plan uses |
  |---|---|
  | (d) migration | `org_identifiers.id` (identity PK), nullable `id_value`, `status` with the ten values of spec §2, `checked_at`, `checked_by`, `check_method` (`document`, `registry`, `manual_check`, `aggregator`), `evidence_document_id`, `source_type`, `evidence`; indexes `org_identifiers_value_uq` and `org_identifiers_open_uq`; `documents.doc_type` accepts `manual_check_evidence`; `source_type` CHECK includes `prior_research` |
  | (d) `research_records.py` | Org findings (`OrgIdentityFinding`, `OrgIdentifierFinding`, `OrgFinancialsFinding`, `OrgLocationFinding`, and the org-side `contact`/`program`/`metric`) carry `source_type` and **`evidence_tier`**. `FindingBase.evidence` is already the quoted sentence, so the tier cannot also be called `evidence` on a finding; the table column is `evidence`. `OrgIdentifierFinding` has `status` and an optional `id_value`. |
  | (d) `writer.py` / `promote.py` | `_may_overwrite(stored, incoming)` and a promotion report with a `conflicts` list |
  | (e) | A `partner` finding on an org research row promotes to the funder's `funder_activity` (`kind = 'partner'`, `partner_org_id` set) |
  | #99 (c) | `app/ingest/source_layouts.py` (`SheetProfile`, `parse_profile`, `_read_blocks`, `normalise_name`), `data/source_layouts/cso_programmes_and_funders.json`, `app/ingest/staff_sources.py` (`search`, `render_row`, `register_dataset`, `hold_unmarked`), `tests/staff_source_fixtures.py` (`cso_workbook`), `read_source_rows` on `ENTITY_RESEARCHER` |

- **No real CSO, funder or person** appears in code, tests, fixtures, skills, prompts, docs or commit messages. Use synthetic names only: "Example Valley Trust", plan (c)'s "Larkspur Learning Trust" and "Moss Valley Society", and `ABCD` as a Give.do code. Source names (Give.do, GuideStar India, the `org-grant-intelligence` repository) are registry entries, not organisations, and may appear.
- **An access rule is a security decision.** Every new or changed registry entry carries its evidence in `basis` and the date someone read robots.txt in `robots_checked_at`. The PR description names the posture change for give.do. C8 lets the researcher read `/discover/` pages that the existing `give` entry's terms-based basis refused. A reviewer must sign that off.
- **`DISPATCHABLE` stays `{open_api, crawl_allowed}`.** Neither new rule is dispatchable, and no adapter is added.
- **Tool conventions** (CLAUDE.md):
  - a tool never raises; it returns `<tool> failed: …`;
  - every catalog row it reports is cited (`[org:N]`, plus `[document:N]` for the evidence);
  - a new tool is registered, named in `instructions.md`, and labelled in `frontend/features/ingest/lib/toolLabels.ts`.
- **Constraints never live only in a skill** (docs/SKILLS.md). The researcher loads no skill (`test_no_subagent_declares_any`). So these hard rules are stated in `prompts/entity_researcher.md` and `instructions.md`, and enforced in code (Tasks 3–6):
  - `applied` is not `registered`;
  - `check_blocked` is not `not_found`;
  - never get past a CAPTCHA or a sign-in;
  - aggregator values are `claimed`;
  - prior-research values are `claimed`.
- **Unit tests never touch a database.** Monkeypatch module functions. Only tests marked `integration` use the compose Postgres on `:5433`.
- **Never run anything against the running site's checkout or its database.** Work in this branch's worktree. The acceptance run (Task 11) uses a scratch database.
- **Style:** ruff, line length 110, py312. `cd backend && ruff check .` is clean after every task. Frontend: `npm run lint && npm run build`. There is no frontend test runner.
- **Commits:** every commit message ends with:

  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  ```

## Review Focus

Five failure modes the happy-path tests would miss. Each one has a test in the task that owns it.

1. **A fetch tool reaches a path outside the allowed list.** This covers an aggregator's `/api/`, its sign-in page, an encoded `..`, a stray query parameter, another commit or another repository on `raw.githubusercontent.com`, or a redirect into any of these.
   - Tests:
     - `TestPathScopedRules` (Task 1);
     - `TestTheRegistryEntries` (Task 2);
     - `TestCheckUrl` (Task 3);
     - `test_a_redirect_off_the_allowed_paths_is_never_requested` and `test_fetch_document_refuses_a_redirect_off_the_allowlist` (Task 4).
2. **An aggregator or prior-research value is stored as evidenced.**
   - Tests:
     - `test_an_aggregator_finding_must_be_claimed` and `test_a_dossier_finding_must_be_prior_research_and_claimed` (Task 5);
     - `test_save_research_refuses_an_aggregator_value_marked_evidenced` (Task 5);
     - `test_promotion_holds_an_aggregator_finding_its_table_cannot_mark_claimed` (Task 5).
3. **A CAPTCHA or sign-in page is treated as "not found" instead of `check_blocked`.**
   - Tests:
     - `TestBlockedPage` (Task 4);
     - `test_a_captcha_page_is_check_blocked_not_text` and `test_a_403_is_check_blocked` (Task 4);
     - `test_not_found_from_an_unreadable_registry_is_refused` (Task 5);
     - `test_a_held_registry_refusal_names_check_blocked` (Task 3).
4. **A manual check is recorded without its evidence document,** or with someone else's document, or by nobody.
   - Tests in `TestRecordRegistryCheck` (Task 6):
     - `test_a_check_without_evidence_writes_nothing`;
     - `test_a_document_of_another_org_is_refused`;
     - `test_no_signed_in_user_writes_nothing`;
     - `test_a_non_staff_user_writes_nothing`.
   - Also `test_the_checker_is_never_an_argument` (Task 7).
5. **A mislabelled workbook block is attributed to the wrong CSO.**
   - Tests:
     - `test_a_block_naming_its_own_cso_as_a_funder_is_held` and `test_the_flag_changes_the_digest` (Task 8);
     - `test_a_held_block_is_shown_without_marker_or_names` (Task 8);
     - `test_the_upload_reports_held_blocks_by_location_only` (Task 8).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `backend/app/ingest/sources.py` | modify | `MANUAL_AGGREGATOR`, `INTERNAL_RESEARCH`, `PATH_SCOPED`; `Source.allowed_paths` / `allowed_query`, `claims_path`, `path_refusal`; `rule_for_url`; self-check |
| `backend/app/ingest/data/sources/ngos.json` | modify | `give_do`, `guidestar_india` (re-hosted), `guidestar_india_site`, `org_grant_intelligence`, `org_grant_intelligence_index`; `hand_vetting_sheets` removed |
| `backend/app/ingest/access.py` | modify | `check_url` via `rule_for_url` with path refusals; `blocked_page`, `check_blocked_reply`, `source_banner` |
| `backend/app/ingest/tools/research_tools.py` | modify | Hooked client, `CHECK BLOCKED`, JSON/plain-text branch, banner |
| `backend/app/ingest/source_guards.py` | create | Pure. Labelling rules at save and at promote |
| `backend/app/ingest/research_records.py` | modify | `EntityResearch` validator calling `source_guards` |
| `backend/app/ingest/promote.py` | modify | `source_guards.hold_at_promote` after (c)'s `hold_unmarked` |
| `backend/app/ingest/manual_checks.py` | create | Validation, lookups and the one write of a manual check |
| `backend/app/ingest/tools/registry_check_tools.py` | create | `record_registry_check` |
| `backend/app/ingest/agent.py` | modify | Register on the supervisor `TOOLS` |
| `backend/app/ingest/instructions.md` | modify | Tool list, registrations section, what you can write |
| `frontend/features/ingest/lib/toolLabels.ts` | modify | Label; `CHECK BLOCKED:` step note |
| `backend/app/ingest/source_layouts.py` | modify | `hold_self_named_blocks`; `_read_blocks` marks held blocks |
| `backend/app/ingest/data/source_layouts/cso_programmes_and_funders.json` | modify | The flag on the funder-details sheet |
| `backend/app/ingest/staff_sources.py` | modify | Held blocks rendered without marker; `held_blocks` |
| `scripts/upload_staff_source.py` | modify | Reports held blocks by location |
| `backend/app/ingest/skills/ngo-credential-research/SKILL.md` | rewrite | Spec §4 and §4a |
| `backend/app/ingest/skills/entity-record/SKILL.md`, `ngo-brief-for-funders/SKILL.md` | modify | Fields now storable |
| `backend/app/ingest/prompts/entity_researcher.md` | modify | Access section; the `org` section rewritten |
| `docs/SKILLS.md`, `docs/INGEST.md` | modify | Path-scoped rules, prior research, manual checks |
| `backend/tests/test_source_access.py` | create | Tasks 1–4 |
| `backend/tests/test_source_guards.py` | create | Task 5 |
| `backend/tests/test_manual_checks.py` | create | Task 6 (unit, plus one integration class); Task 7 adds the tool's tests |
| `backend/tests/test_harness.py`, `test_ingest.py`, `test_source_layouts.py`, `test_staff_sources.py`, `staff_source_fixtures.py` | modify | Pins, skills, the held block |

---

### Task 1: Path-scoped access rules in the registry model

**Files:**
- Modify: `backend/app/ingest/sources.py`
- Test: `backend/tests/test_source_access.py` (create)

**Interfaces:**

```python
class AccessRule(StrEnum): ...; MANUAL_AGGREGATOR = "manual_aggregator"; INTERNAL_RESEARCH = "internal_research"
PATH_SCOPED: frozenset[AccessRule]
@dataclass(frozen=True, slots=True) class Source: ...; allowed_paths: tuple[str, ...] = (); allowed_query: tuple[tuple[str, str | None], ...] = ()
    @property def path_scoped(self) -> bool
    def claims_path(self, path: str) -> bool
    def path_refusal(self, path: str, query: str) -> str | None
def rule_for_url(url: str) -> tuple[AccessRule, Source] | None
```

- [ ] **Step 1: Verify the preconditions**

```bash
cd backend
grep -n "evidence_tier" app/ingest/research_records.py
grep -n "prior_research" app/ingest/research_records.py ../db/migrations/*.sql
grep -n "check_blocked" app/ingest/research_records.py
grep -n "evidence_document_id\|check_method\|org_identifiers_open_uq" ../db/migrations/*.sql
grep -n "manual_check_evidence" ../db/migrations/*.sql
grep -n "def _may_overwrite" app/ingest/writer.py
grep -n "\"conflicts\"" app/ingest/promote.py
grep -n "def hold_unmarked\|^async def search\|^def render_row\|^async def register_dataset" app/ingest/staff_sources.py
grep -n "^def _read_blocks\|^class SheetProfile\|^def parse_profile" app/ingest/source_layouts.py
grep -n "read_source_rows" app/ingest/agent.py
```

Expected: every command prints at least one line. If any prints nothing, stop. Report which interface is missing, and do not start Step 2.

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_source_access.py`:

```python
"""Path-scoped access rules: what the researcher may read on an aggregator or the research repo.

A path-scoped entry governs only the paths it names. Everything else on its host falls back to
the strictest other rule there, or is refused when there is none.
"""

from __future__ import annotations

from datetime import date
from types import MappingProxyType

import pytest

from app.ingest import sources
from app.ingest.sources import (
    DISPATCHABLE,
    PATH_SCOPED,
    AccessRule,
    Category,
    Source,
    rule_for_host,
    rule_for_url,
)


def _source(key: str, host: str, rule: AccessRule, *, paths=(), query=(), checked=date(2026, 10, 7)) -> Source:
    return Source(
        key=key, name=f"Test {key}", host=host, access_rule=rule,
        basis="A synthetic entry for tests; the basis has to be longer than a verdict.",
        categories=frozenset({Category.NGO}), yields=("org",), robots_checked_at=checked,
        allowed_paths=tuple(paths), allowed_query=tuple(query),
    )


AGG = _source("agg", "agg.example", AccessRule.MANUAL_AGGREGATOR, paths=("/discover/",))
API = _source("api", "api.example", AccessRule.MANUAL_AGGREGATOR,
              paths=("/api/method/directory.search",), query=(("keyword", None), ("page_no", None)))
REPO = _source("repo", "raw.example", AccessRule.INTERNAL_RESEARCH,
               paths=("/team/research/0123456789abcdef0123456789abcdef01234567/",))
INDEX = _source("index", "index.example", AccessRule.INTERNAL_RESEARCH,
                paths=("/repos/team/research/contents/",),
                query=(("ref", "0123456789abcdef0123456789abcdef01234567"),))
HELD = _source("held", "agg.example", AccessRule.NO_SCRAPING)


class TestPathScopedRules:
    def test_the_new_rules_are_never_dispatchable(self):
        assert PATH_SCOPED == {AccessRule.MANUAL_AGGREGATOR, AccessRule.INTERNAL_RESEARCH}
        assert not PATH_SCOPED & DISPATCHABLE
        assert not AGG.dispatchable and not REPO.dispatchable

    def test_every_refusing_rule_is_stricter_than_a_path_scoped_one(self):
        order = sources._STRICTNESS
        assert set(order) == set(AccessRule), "a rule missing from _STRICTNESS raises in max()"
        for scoped in PATH_SCOPED:
            for rule in set(AccessRule) - PATH_SCOPED - DISPATCHABLE:
                assert order.index(rule) > order.index(scoped), (rule, scoped)

    @pytest.mark.parametrize("path", ["/discover/ABCD/example-valley-trust/", "/discover/ABCD"])
    def test_a_profile_under_an_allowed_prefix_is_readable(self, path):
        assert AGG.path_refusal(path, "") is None

    @pytest.mark.parametrize(
        ("path", "query", "why"),
        [
            ("/api/v1/ngo/ABCD", "", "only /discover/"),
            ("/discover/", "", "only /discover/"),                     # the listing itself is not a profile
            ("/discover/login", "", "sign-in"),
            ("/discover/ABCD/account/", "", "sign-in"),
            ("/discover/../api/v1/ngo", "", "normal form"),
            ("/discover/%2e%2e/api/v1/ngo", "", "normal form"),
            ("/discover//api", "", "normal form"),
            ("/discover/ABCD/", "utm_source=x", "'utm_source'"),
        ],
    )
    def test_anything_else_on_an_aggregator_is_refused(self, path, query, why):
        refusal = AGG.path_refusal(path, query)
        assert refusal is not None and why in refusal

    def test_an_exact_api_path_takes_only_its_parameters(self):
        assert API.path_refusal("/api/method/directory.search", "keyword=Example+Valley+Trust&page_no=1") is None
        assert API.path_refusal("/api/method/directory.profile", "keyword=x&page_no=1") is not None
        assert API.path_refusal("/api/method/directory.search/x", "keyword=x") is not None
        assert "'cmd'" in API.path_refusal("/api/method/directory.search", "keyword=x&cmd=other")

    def test_a_pinned_parameter_must_carry_its_value(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        assert INDEX.path_refusal("/repos/team/research/contents/ngos", f"ref={sha}") is None
        assert "must be" in INDEX.path_refusal("/repos/team/research/contents/ngos", "ref=main")
        assert "must be given" in INDEX.path_refusal("/repos/team/research/contents/ngos", "")

    def test_the_research_repo_is_readable_only_at_its_commit(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        assert REPO.path_refusal(f"/team/research/{sha}/ngos/example/profile.md", "") is None
        assert REPO.path_refusal("/team/research/main/ngos/example/profile.md", "") is not None
        assert REPO.path_refusal(f"/team/other-repo/{sha}/x.md", "") is not None
        assert REPO.path_refusal(f"/someone/research/{sha}/x.md", "") is not None


class TestRuleForUrl:
    @pytest.fixture(autouse=True)
    def registry(self, monkeypatch):
        entries = {s.key: s for s in (AGG, API, REPO, INDEX, HELD)}
        monkeypatch.setattr(sources, "SOURCES", MappingProxyType(entries))

    def test_a_claimed_path_is_governed_by_its_path_scoped_entry(self):
        rule, source = rule_for_url("https://agg.example/discover/ABCD/example-valley-trust/")
        assert (rule, source.key) == (AccessRule.MANUAL_AGGREGATOR, "agg")

    def test_any_other_path_falls_back_to_the_strictest_other_rule(self):
        rule, source = rule_for_url("https://agg.example/api/v1/ngo/ABCD")
        assert (rule, source.key) == (AccessRule.NO_SCRAPING, "held")

    def test_a_host_with_only_a_path_scoped_entry_returns_it_so_the_path_check_refuses(self):
        rule, source = rule_for_url("https://raw.example/team/other-repo/x.md")
        assert source.key == "repo"
        assert source.path_refusal("/team/other-repo/x.md", "") is not None

    def test_an_unregistered_host_has_no_rule(self):
        assert rule_for_url("https://unknown.example/x") is None


def test_hosts_without_path_scoped_entries_resolve_as_before():
    for host in ("mcacdm.nic.in", "csr.gov.in", "indiacsr.in"):
        assert rule_for_url(f"https://{host}/any/path") == rule_for_host(host)


class TestTheSelfCheck:
    @pytest.mark.parametrize(
        ("bad", "message"),
        [
            (_source("x", "", AccessRule.MANUAL_AGGREGATOR, paths=("/a/",)), "names one host"),
            (_source("x", "x.example", AccessRule.MANUAL_AGGREGATOR), "lists the paths"),
            (_source("x", "x.example", AccessRule.INTERNAL_RESEARCH, paths=("/a/",), checked=None), "robots"),
            (_source("x", "x.example", AccessRule.MANUAL_AGGREGATOR, paths=("/",)), "below the root"),
            (_source("x", "x.example", AccessRule.MANUAL_AGGREGATOR, paths=("/a/../b/",)), "below the root"),
            (_source("x", "x.example", AccessRule.CRAWL_ALLOWED, paths=("/a/",)), "path-scoped sources only"),
        ],
    )
    def test_a_malformed_path_scoped_entry_fails_at_import(self, monkeypatch, bad, message):
        monkeypatch.setattr(sources, "_SOURCES", (bad,))
        with pytest.raises(ValueError, match=message):
            sources._self_check()
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_source_access.py -q`
Expected: collection error, `ImportError: cannot import name 'PATH_SCOPED'`.

- [ ] **Step 4: Implement**

In `backend/app/ingest/sources.py`:

(a) Extend the imports:

```python
import json
import posixpath
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from importlib.resources import files
from types import MappingProxyType
from urllib.parse import parse_qsl, unquote, urlparse
```

(b) Add the two members at the end of `AccessRule`, and change its docstring to read: `"""The legend from the source inventory. Only open_api and crawl_allowed are dispatchable; the two path-scoped rules are read by the researcher's fetch tools on named paths only."""`

```python
    MANUAL_AGGREGATOR = "manual_aggregator"
    INTERNAL_RESEARCH = "internal_research"
```

(c) After `DISPATCHABLE`, add:

```python
# Read by the researcher's fetch tools one URL at a time, on the paths the entry names and no
# others, never by an adapter. An aggregator's values are always claimed; so are the team's own
# earlier research files until a primary source is re-read (spec C8, C14).
PATH_SCOPED: frozenset[AccessRule] = frozenset({AccessRule.MANUAL_AGGREGATOR, AccessRule.INTERNAL_RESEARCH})

# Nothing behind a sign-in is read on a path-scoped source, whatever its allowlist says.
_SIGN_IN = re.compile(
    r"/(?:login|log-in|logout|signin|sign-in|signup|sign-up|auth|oauth|sso|account|accounts|admin|dashboard)"
    r"(?:[/.]|$)",
    re.I,
)
```

(d) Replace `_STRICTNESS` with:

```python
_STRICTNESS: tuple[AccessRule, ...] = (
    AccessRule.OPEN_API,
    AccessRule.CRAWL_ALLOWED,
    # Path-scoped rules sit just above the dispatchable ones: on a host they share with any
    # refusing rule, the refusal wins everywhere the path-scoped entry does not claim the path.
    AccessRule.INTERNAL_RESEARCH,
    AccessRule.MANUAL_AGGREGATOR,
    AccessRule.CRAWL_PER_SITE,
    AccessRule.CRAWL_WITH_PERMISSION,
    AccessRule.NOT_CHECKED,
    AccessRule.REFERENCE_ONLY,
    AccessRule.LICENCE_NEEDED,
    AccessRule.PARTNER_PERMISSION,
    AccessRule.NO_SCRAPING,
    AccessRule.MANUAL_ONLY,
)
```

(e) Add two fields at the end of `Source`, after `robots_checked_at`, and its methods after `is_site_class`:

```python
    allowed_paths: tuple[str, ...] = ()
    """Path-scoped rules only: the paths that may be read. One ending in "/" is a prefix and
    needs something below it; any other is exact."""
    allowed_query: tuple[tuple[str, str | None], ...] = ()
    """Path-scoped rules only: the query parameters a URL may carry, each with the one value it
    must have, or None for any value. Empty means no query string at all."""

    @property
    def path_scoped(self) -> bool:
        return self.access_rule in PATH_SCOPED

    def claims_path(self, path: str) -> bool:
        """Whether this entry governs the path at all. Not whether it may be read: see path_refusal."""
        raw = unquote(path or "/")
        return any(
            raw == p or (p.endswith("/") and raw.startswith(p) and len(raw) > len(p))
            for p in self.allowed_paths
        )

    def path_refusal(self, path: str, query: str) -> str | None:
        """None when a path-scoped source may read this path and query, else the reason it may not."""
        raw = unquote(path or "/")
        norm = posixpath.normpath(raw)
        if raw.endswith("/") and norm != "/":
            norm += "/"
        if norm != raw or "//" in raw or "\\" in raw:
            return f"the path {raw!r} is not in normal form, so it is not read"
        if _SIGN_IN.search(raw):
            return "it is a sign-in or account page, and nothing behind a sign-in is read"
        if not self.claims_path(raw):
            return f"only {', '.join(self.allowed_paths)} may be read on {self.host}"
        allowed = dict(self.allowed_query)
        given = parse_qsl(query or "", keep_blank_values=True)
        for key, value in given:
            if key not in allowed:
                return f"the query parameter {key!r} is not one this source allows"
            if allowed[key] is not None and value != allowed[key]:
                return f"{key} must be {allowed[key]!r} here"
        missing = [k for k, v in allowed.items() if v is not None and k not in dict(given)]
        if missing:
            return f"{', '.join(missing)} must be given, pinned to {', '.join(repr(allowed[k]) for k in missing)}"
        return None
```

(f) In `_load()`, pass the two new fields to `Source(...)`:

```python
                    allowed_paths=tuple(entry.get("allowed_paths", ())),
                    allowed_query=tuple((k, v) for k, v in entry.get("allowed_query", {}).items()),
```

(g) After `rule_for_host`, add:

```python
def rule_for_url(url: str) -> tuple[AccessRule, Source] | None:
    """The rule governing this URL, which on a host with a path-scoped entry depends on the path.

    A path-scoped entry governs only the paths it claims. Every other path falls back to the
    strictest of the host's other entries. On a host with no other entry, the path-scoped entry
    is returned anyway, so its path_refusal turns the URL away instead of the host reading as
    unclassified (and so readable).
    """
    parsed = urlparse(url)
    found = sources_on_host(parsed.hostname or "")
    if not found:
        return None
    scoped = [s for s in found if s.path_scoped]
    for source in scoped:
        if source.claims_path(parsed.path):
            return source.access_rule, source
    rest = [s for s in found if not s.path_scoped] or scoped
    strictest = max(rest, key=lambda s: _STRICTNESS.index(s.access_rule))
    return strictest.access_rule, strictest
```

(h) At the end of the loop in `_self_check()`, add:

```python
        if source.path_scoped:
            if not source.host:
                raise ValueError(f"{source.key}: a path-scoped source names one host")
            if not source.allowed_paths:
                raise ValueError(f"{source.key}: a path-scoped source lists the paths it may read")
            if source.robots_checked_at is None:
                raise ValueError(f"{source.key}: path-scoped but nobody recorded a robots check")
            for p in source.allowed_paths:
                if not p.startswith("/") or p == "/" or posixpath.normpath(p).rstrip("/") != p.rstrip("/"):
                    raise ValueError(f"{source.key}: {p!r} is not a normal path below the root")
        elif source.allowed_paths or source.allowed_query:
            raise ValueError(f"{source.key}: allowed_paths and allowed_query belong to path-scoped sources only")
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && pytest tests/test_source_access.py tests/test_ingest.py -q -k "Path or RuleForUrl or SelfCheck or resolve_as_before or Sources"`
Expected: all pass. `test_ingest.py`'s `TestSourcesGateOnAccessRules` is unchanged and passes.

Run: `cd backend && ruff check .`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingest/sources.py backend/tests/test_source_access.py
git commit -m "feat(ingest): path-scoped access rules for aggregators and internal research

manual_aggregator and internal_research govern only the paths an entry names;
every other path on the host falls back to its strictest other rule. Neither is
dispatchable. The self-check refuses a path-scoped entry with no host, no paths
or no robots check.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The registry entries

**Files:**
- Modify: `backend/app/ingest/data/sources/ngos.json`
- Test: `backend/tests/test_source_access.py`

**Interfaces:** registry keys `give_do`, `guidestar_india`, `guidestar_india_site`, `org_grant_intelligence` and `org_grant_intelligence_index`. `hand_vetting_sheets` is removed. `give` in `funders.json` is unchanged and still pinned by `test_a_restricted_source_is_registered_but_never_dispatched`.

The pinned commit is `414cd6968765bcfff758632797dcbb8d00363ab2`. That is the full SHA of `414cd69`, the commit Sangam's seed was copied from (spec §4a).

- [ ] **Step 1: Read the four robots files and record the date**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://give.do/robots.txt && curl -s https://give.do/robots.txt | grep -i "disallow"
curl -s -w "\n%{http_code} %{size_download}\n" https://guidestarindia.frappe.cloud/robots.txt
curl -s -o /dev/null -w "%{http_code}\n" https://raw.githubusercontent.com/robots.txt
curl -s -o /dev/null -w "%{http_code}\n" https://api.github.com/robots.txt
curl -s "https://guidestarindia.frappe.cloud/api/method/guidestar.api.npo_profile.npo_profile_search" | head -c 200
git ls-remote https://github.com/project-tech4dev/org-grant-intelligence.git | head -3
```

Expected, as read on 2026-10-07:
- give.do: `200`, with `Disallow: /api/`, `/discover/login` and `/login` among the lines. `/discover/` itself is not disallowed.
- guidestarindia.frappe.cloud: `200 0`, served and empty, so nothing is disallowed.
- raw.githubusercontent.com: `404`, which means no restrictions (RFC 9309).
- api.github.com: `404`.
- The API call: a `TypeError` naming the two required arguments, `keyword` and `page_no`.
- `414cd69…` is reachable. It need not be `HEAD`; the pin is deliberate.

If any line differs, **stop and report**. A new `Disallow` on an allowed path, or a different parameter name, changes what this task may register. Use the date you ran this as `robots_checked_at` below, in place of `2026-10-07` if it differs.

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_source_access.py`:

```python
SHA = "414cd6968765bcfff758632797dcbb8d00363ab2"
REPO_ROOT = f"https://raw.githubusercontent.com/project-tech4dev/org-grant-intelligence/{SHA}/"


class TestTheRegistryEntries:
    """The real JSON. Every URL is synthetic apart from the hosts and the repository."""

    def test_give_do_is_an_aggregator_on_discover_pages_only(self):
        source = sources.SOURCES["give_do"]
        assert (source.access_rule, source.host, source.allowed_paths) == (
            AccessRule.MANUAL_AGGREGATOR, "give.do", ("/discover/",))
        assert rule_for_url("https://give.do/discover/ABCD/example-valley-trust/")[1].key == "give_do"

    @pytest.mark.parametrize("path", ["/api/v1/ngo/ABCD", "/fundraisers/x", "/"])
    def test_the_rest_of_give_do_keeps_its_refusal(self, path):
        rule, source = rule_for_url(f"https://give.do{path}")
        assert (rule, source.key) == (AccessRule.NO_SCRAPING, "give")

    def test_guidestar_is_its_search_api_and_nothing_else(self):
        source = sources.SOURCES["guidestar_india"]
        assert source.host == "guidestarindia.frappe.cloud"
        assert source.allowed_paths == ("/api/method/guidestar.api.npo_profile.npo_profile_search",)
        assert dict(source.allowed_query) == {"keyword": None, "page_no": None}

    def test_the_guidestar_site_stays_closed(self):
        rule, source = rule_for_url("https://guidestarindia.org/profile/example-valley-trust")
        assert source.key == "guidestar_india_site" and not source.dispatchable and not source.path_scoped

    def test_the_research_repo_is_pinned_to_one_commit(self):
        source = sources.SOURCES["org_grant_intelligence"]
        assert (source.access_rule, source.host) == (AccessRule.INTERNAL_RESEARCH, "raw.githubusercontent.com")
        assert source.allowed_paths == (f"/project-tech4dev/org-grant-intelligence/{SHA}/",)
        index = sources.SOURCES["org_grant_intelligence_index"]
        assert index.allowed_paths == ("/repos/project-tech4dev/org-grant-intelligence/contents/",)
        assert dict(index.allowed_query) == {"ref": SHA}

    @pytest.mark.parametrize(
        "url",
        [
            "https://raw.githubusercontent.com/project-tech4dev/org-grant-intelligence/main/ngos/x/profile.md",
            "https://raw.githubusercontent.com/project-tech4dev/another-repo/" + SHA + "/x.md",
            "https://raw.githubusercontent.com/someone-else/org-grant-intelligence/" + SHA + "/x.md",
            "https://api.github.com/repos/project-tech4dev/another-repo/contents/x",
            "https://api.github.com/users/someone",
        ],
    )
    def test_any_other_path_on_those_hosts_is_refused(self, url):
        from urllib.parse import urlparse

        found = rule_for_url(url)
        assert found is not None, "an unregistered path would read as unclassified, and so readable"
        parsed = urlparse(url)
        assert found[1].path_refusal(parsed.path, parsed.query) is not None

    def test_the_hand_vetting_entry_is_folded_into_the_repo(self):
        assert "hand_vetting_sheets" not in sources.SOURCES

    def test_no_new_entry_is_dispatchable(self):
        for key in ("give_do", "guidestar_india", "guidestar_india_site",
                    "org_grant_intelligence", "org_grant_intelligence_index"):
            assert not sources.SOURCES[key].dispatchable, key
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_source_access.py -q -k RegistryEntries`
Expected: `KeyError: 'give_do'`, plus failures on the GuideStar host and the repository entries.

- [ ] **Step 4: Edit `ngos.json`**

(a) Replace the whole `guidestar_india` object with these two:

```json
    {
      "key": "guidestar_india",
      "name": "GuideStar India public search (CSIS India)",
      "host": "guidestarindia.frappe.cloud",
      "access_rule": "manual_aggregator",
      "categories": ["ngo"],
      "yields": ["org"],
      "allowed_paths": ["/api/method/guidestar.api.npo_profile.npo_profile_search"],
      "allowed_query": {"keyword": null, "page_no": null},
      "basis": "The search endpoint behind guidestarindia.org's public search page answers without sign-in, and robots.txt on this host is served empty (nothing disallowed). Only that one method is called, with keyword and page_no, one CSO at a time on a staff request. Nothing behind a sign-in is read. Every value is claimed: it is GuideStar's account, not the CSO's own documents. Terms of use were not read, so check them before Sangam displays its certification levels publicly.",
      "robots_checked_at": "2026-10-07"
    },
    {
      "key": "guidestar_india_site",
      "name": "GuideStar India website and profiles",
      "host": "guidestarindia.org",
      "access_rule": "no_scraping_manual_entry_allowed",
      "categories": ["ngo"],
      "yields": ["org"],
      "basis": "robots.txt allows all paths, but Sangam reads GuideStar India only through its public search API (guidestar_india) and never anything behind its sign-in. A person may read a profile by hand and cite it.",
      "robots_checked_at": "2026-09-28"
    },
```

(b) Add after `ngo_annual_reports`:

```json
    {
      "key": "give_do",
      "name": "Give.do public NGO pages",
      "host": "give.do",
      "access_rule": "manual_aggregator",
      "categories": ["ngo"],
      "yields": ["org"],
      "allowed_paths": ["/discover/"],
      "basis": "Read under spec C8 as a manual aggregator: one CSO's public /discover/ page at a time, on a staff request, low volume. robots.txt (checked 2026-10-07) disallows /api/, /login and /discover/login, and none of those is read. Every other path stays under the give entry, whose terms-based refusal still governs. Every value is claimed, cited with its page URL, and never replaces the CSO's own document.",
      "robots_checked_at": "2026-10-07"
    },
```

(c) Replace the whole `hand_vetting_sheets` object with:

```json
    {
      "key": "org_grant_intelligence",
      "name": "org-grant-intelligence research repository (pinned)",
      "host": "raw.githubusercontent.com",
      "access_rule": "internal_research",
      "categories": ["ngo", "funder"],
      "yields": ["org", "funder"],
      "allowed_paths": ["/project-tech4dev/org-grant-intelligence/414cd6968765bcfff758632797dcbb8d00363ab2/"],
      "basis": "The team's own earlier research, a public GitHub repository: CSO and funder dossiers, hand-vetting sheets, Darpan extracts. Read at one pinned commit, the one the seed was copied from, so a citation never moves. Facts carry the dossier's cited source; re-verify against that source before treating any as evidenced, and until then each is prior_research and claimed. robots.txt on this host answered 404 (no restrictions).",
      "robots_checked_at": "2026-10-07"
    },
    {
      "key": "org_grant_intelligence_index",
      "name": "org-grant-intelligence directory listings (pinned)",
      "host": "api.github.com",
      "access_rule": "internal_research",
      "categories": ["ngo", "funder"],
      "yields": ["org", "funder"],
      "allowed_paths": ["/repos/project-tech4dev/org-grant-intelligence/contents/"],
      "allowed_query": {"ref": "414cd6968765bcfff758632797dcbb8d00363ab2"},
      "basis": "Directory listings of the same repository at the same pinned commit, so a researcher can find a dossier's file names; each entry's download_url is the pinned raw URL. Nothing else on api.github.com is read. robots.txt answered 404 (no restrictions). Unauthenticated, so GitHub allows about sixty calls an hour.",
      "robots_checked_at": "2026-10-07"
    },
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && pytest tests/test_source_access.py tests/test_ingest.py -q`
Expected: all pass. The import-time `_self_check()` accepts every new entry, and `test_a_restricted_source_is_registered_but_never_dispatched[give]` still passes.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingest/data/sources/ngos.json backend/tests/test_source_access.py
git commit -m "feat(ingest): register Give.do, GuideStar's search API and the research repo

give_do and guidestar_india are manual aggregators on named paths; the rest of
give.do keeps its no-scraping rule and guidestarindia.org stays closed.
org_grant_intelligence replaces hand_vetting_sheets: the whole repository, read
only at the commit the seed was copied from.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `check_url` reads by URL, not by host

**Files:**
- Modify: `backend/app/ingest/access.py`
- Test: `backend/tests/test_source_access.py`

**Interfaces:** `check_url(url) -> str | None` keeps its signature. New in `access.py`: `source_banner(url: str) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_source_access.py`:

```python
from app.ingest import access


@pytest.fixture
def robots(monkeypatch):
    """robots.txt allows everything unless a test says otherwise; no proposal is written."""
    state = {"allowed": True, "asked": []}

    async def allows(scheme, host, url):
        state["asked"].append(url)
        return state["allowed"]

    async def note(host, url, *, robots_result):
        return None

    monkeypatch.setattr(access, "_robots_allows", allows)
    monkeypatch.setattr(access, "_note_proposal", note)
    return state


class TestCheckUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://give.do/discover/ABCD/example-valley-trust/",
            "https://guidestarindia.frappe.cloud/api/method/guidestar.api.npo_profile.npo_profile_search"
            "?keyword=Example+Valley+Trust&page_no=1",
            REPO_ROOT + "ngos/example-valley-trust/profile.md",
            "https://api.github.com/repos/project-tech4dev/org-grant-intelligence/contents/ngos?ref=" + SHA,
        ],
    )
    async def test_an_allowed_path_is_readable_and_robots_is_still_asked(self, robots, url):
        assert await access.check_url(url) is None
        assert robots["asked"] == [url]

    @pytest.mark.parametrize(
        ("url", "says"),
        [
            ("https://give.do/api/v1/ngo/ABCD", "no_scraping"),
            ("https://give.do/discover/login", "sign-in"),
            ("https://give.do/discover/ABCD/?utm_source=x", "'utm_source'"),
            ("https://guidestarindia.frappe.cloud/api/method/frappe.auth.get_logged_user", "only /api/method"),
            ("https://guidestarindia.org/profile/example-valley-trust", "no_scraping"),
            ("https://raw.githubusercontent.com/project-tech4dev/org-grant-intelligence/main/x.md", "only /"),
            ("https://raw.githubusercontent.com/someone-else/any-repo/" + SHA + "/x.md", "only /"),
            ("https://api.github.com/repos/project-tech4dev/org-grant-intelligence/contents/ngos?ref=main",
             "must be"),
        ],
    )
    async def test_everything_else_is_refused_before_robots_is_read(self, robots, url, says):
        refusal = await access.check_url(url)
        assert refusal is not None and says in refusal
        assert robots["asked"] == []

    async def test_robots_still_decides_within_an_allowed_path(self, robots):
        robots["allowed"] = False
        refusal = await access.check_url("https://give.do/discover/ABCD/example-valley-trust/")
        assert refusal is not None and "robots.txt" in refusal

    async def test_a_held_registry_refusal_names_check_blocked(self, robots):
        refusal = await access.check_url("https://ngodarpan.gov.in/index.php/search/")
        assert "check_blocked" in refusal and "never not_found" in refusal

    async def test_a_held_funder_source_does_not_mention_registrations(self, robots):
        refusal = await access.check_url("https://mcacdm.nic.in/x")
        assert refusal is not None and "check_blocked" not in refusal


class TestSourceBanner:
    def test_an_aggregator_page_says_claimed(self):
        banner = access.source_banner("https://give.do/discover/ABCD/example-valley-trust/")
        assert "source_type 'aggregator'" in banner and "evidence_tier 'claimed'" in banner

    def test_a_dossier_says_prior_research(self):
        banner = access.source_banner(REPO_ROOT + "ngos/example-valley-trust/profile.md")
        assert "source_type 'prior_research'" in banner and "re-read the links" in banner

    def test_an_ordinary_page_has_none(self):
        assert access.source_banner("https://example-valley-trust.example/about") == ""
```

`mcacdm.nic.in` carries only `funder` products, so its refusal must not mention registrations. Check the registry before you rely on it. If an `ngo` product on that host exists, use `csr.gov.in` instead.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_source_access.py -q -k "CheckUrl or Banner"`
Expected: the aggregator URLs are refused (`give.do` resolves to `give` by host), `check_blocked` is missing from the Darpan refusal, and `AttributeError: … 'source_banner'`.

- [ ] **Step 3: Implement**

In `backend/app/ingest/access.py`, change the import to:

```python
from app.ingest.sources import AccessRule, Category, rule_for_url
```

Add, after `_ROBOTS`:

```python
# A held registry an organisation's registration would be confirmed on. A refusal there is a
# fact about Sangam's access, not about the registration.
_REGISTRY_RULES = frozenset({AccessRule.MANUAL_ONLY, AccessRule.NO_SCRAPING})
```

Replace the block from `found = rule_for_host(host)` down to and including the existing `return (… not be read automatically …)` with:

```python
    # rule_for_url, not rule_for_host: a path-scoped entry (an aggregator, the research repo)
    # governs only the paths it names, and every other path on its host keeps the host's
    # strictest rule. Several products share some hosts (mcacdm.nic.in has four).
    found = rule_for_url(url)
    source = found[1] if found else None
    if source is not None and source.path_scoped:
        why = source.path_refusal(parsed.path, parsed.query)
        if why:
            return (
                f"{source.name} ({source.host}) is registered as {source.access_rule.value}, and {why}. "
                f"{source.basis} Report this; do not look for another route to the same content."
            )
    elif source is not None and not source.dispatchable:
        refusal = (
            f"{source.name} ({source.host}) is registered as {source.access_rule.value} and must "
            f"not be read automatically. {source.basis} Report this to the user; do not look for "
            f"another route to the same content."
        )
        if source.access_rule in _REGISTRY_RULES and Category.NGO in source.categories:
            refusal += (
                " If this is where a registration would be confirmed, record its status as "
                "check_blocked - never not_found - and say a person must check it by hand."
            )
        return refusal
```

The robots logic below it is unchanged. A path-scoped URL that passes its path check still has robots.txt asked about it. A registered path-scoped source whose robots.txt cannot be read is treated like any other registered source: someone checked it and recorded the date.

Append:

```python
def source_banner(url: str) -> str:
    """The line a fetch tool puts above a page's text when its source decides how it is labelled."""
    found = rule_for_url(url)
    if found is None:
        return ""
    rule, source = found
    if rule is AccessRule.MANUAL_AGGREGATOR:
        return (
            f"[{source.name} is an aggregator. Every value below is claimed: save it with "
            f"source_type 'aggregator' and evidence_tier 'claimed', as a lead or a corroboration, "
            f"never in place of the organisation's own document.]\n\n"
        )
    if rule is AccessRule.INTERNAL_RESEARCH:
        return (
            f"[{source.name}: Sangam's earlier research, pinned to one commit. Every value below is "
            f"claimed: save it with source_type 'prior_research' and evidence_tier 'claimed', citing "
            f"this URL, then re-read the links it cites under their own access rules.]\n\n"
        )
    return ""
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && pytest tests/test_source_access.py tests/test_storage.py tests/test_ingest.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingest/access.py backend/tests/test_source_access.py
git commit -m "feat(ingest): check_url decides by URL; held registries say check_blocked

A path-scoped entry refuses any path, query or sign-in page it does not name
before robots.txt is read. A refusal from a held NGO registry tells the model
the registration is check_blocked, never not_found.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The fetch tools — every redirect hop checked, blocked pages, JSON and plain text

**Files:**
- Modify: `backend/app/ingest/access.py` (add `blocked_page`, `check_blocked_reply`)
- Modify: `backend/app/ingest/tools/research_tools.py`
- Modify: `frontend/features/ingest/lib/toolLabels.ts` (step note only)
- Test: `backend/tests/test_source_access.py`

**Interfaces:**

```python
READABLE_FLOOR = 1_500       # access.py
BLOCK_SCAN_CHARS = 50_000
def blocked_page(status: int, url: str, html: str, *, readable_chars: int) -> str | None
def check_blocked_reply(url: str, reason: str) -> str          # starts "CHECK BLOCKED: "
class _Stop(Exception): reply: str                              # research_tools.py
def _client(original: str, **kwargs) -> httpx.AsyncClient
def _compact_json(text: str) -> str
```

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_source_access.py`:

```python
import httpx

from app.ingest.tools import research_tools as research

LONG = "The trust runs village reading rooms and trains volunteer teachers in three districts. " * 30


class TestBlockedPage:
    @pytest.mark.parametrize(("status", "word"), [(401, "sign-in"), (403, "403"), (407, "sign-in"), (429, "429")])
    def test_a_refusing_status_is_blocked(self, status, word):
        assert word in access.blocked_page(status, "https://x.example/a", "", readable_chars=0)

    @pytest.mark.parametrize("path", ["/login", "/users/sign_in", "/account/login/", "/signin?next=/a"])
    def test_a_sign_in_path_is_blocked(self, path):
        assert access.blocked_page(200, f"https://x.example{path}", "", readable_chars=5000) == "a sign-in page"

    def test_a_short_captcha_page_is_blocked(self):
        html = '<form><div class="g-recaptcha"></div><img src="captcha.php"></form>'
        assert access.blocked_page(200, "https://x.example/search", html, readable_chars=40) == "a CAPTCHA"

    def test_a_short_password_form_is_blocked(self):
        html = '<form><input name="u"><input type="password" name="p"></form>'
        assert access.blocked_page(200, "https://x.example/x", html, readable_chars=40) == "a sign-in form"

    def test_a_long_page_with_a_contact_form_captcha_is_read(self):
        html = f'<article>{LONG}</article><form><div class="g-recaptcha"></div></form>'
        assert access.blocked_page(200, "https://x.example/about", html, readable_chars=len(LONG)) is None

    def test_a_404_is_not_blocked(self):
        assert access.blocked_page(404, "https://x.example/gone", "", readable_chars=0) is None

    def test_the_reply_says_check_blocked_and_not_not_found(self):
        reply = access.check_blocked_reply("https://x.example/a", "a CAPTCHA")
        assert reply.startswith("CHECK BLOCKED:") and "check_blocked" in reply and "not 'not found'" in reply


@pytest.fixture
def web(monkeypatch, robots, tmp_path):
    """A fake internet: pages by URL, and a record of every request actually sent."""
    pages: dict[str, httpx.Response] = {}
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return pages.get(str(request.url), httpx.Response(404))

    real = httpx.AsyncClient
    monkeypatch.setattr(research.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(research, "downloads_dir", lambda: tmp_path)

    async def no_upload(*a, **kw):
        return None

    monkeypatch.setattr(research.storage, "upload", no_upload)
    return pages, sent


GIVE = "https://give.do/discover/ABCD/example-valley-trust/"
HTML = {"content-type": "text/html; charset=utf-8"}


class TestTheFetchTools:
    async def test_a_redirect_off_the_allowed_paths_is_never_requested(self, web):
        pages, sent = web
        pages[GIVE] = httpx.Response(302, headers={"location": "https://give.do/api/v1/ngo/ABCD"})
        result = await research.read_page.ainvoke({"url": GIVE})
        assert result.startswith("REFUSED:") and "redirected to" in result
        assert sent == [GIVE], "the /api/ hop must be refused before it is requested"

    async def test_a_redirect_to_a_sign_in_page_is_check_blocked(self, web):
        pages, sent = web
        pages[GIVE] = httpx.Response(302, headers={"location": "https://give.do/discover/login?next=/x"})
        result = await research.read_page.ainvoke({"url": GIVE})
        assert result.startswith("CHECK BLOCKED:")
        assert sent == [GIVE]

    async def test_a_captcha_page_is_check_blocked_not_text(self, web):
        pages, _ = web
        url = "https://example-valley-trust.example/registry-lookup"
        pages[url] = httpx.Response(200, headers=HTML, text='<form><div class="g-recaptcha"></div></form>')
        result = await research.read_page.ainvoke({"url": url})
        assert result.startswith("CHECK BLOCKED:") and "a CAPTCHA" in result

    async def test_a_403_is_check_blocked(self, web):
        pages, _ = web
        url = "https://example-valley-trust.example/annual-report"
        pages[url] = httpx.Response(403)
        assert (await research.read_page.ainvoke({"url": url})).startswith("CHECK BLOCKED:")

    async def test_an_aggregator_page_is_read_under_its_banner(self, web):
        pages, _ = web
        pages[GIVE] = httpx.Response(200, headers=HTML,
                                     text=f"<html><body><article><h1>Example Valley Trust</h1><p>{LONG}</p>"
                                          f"</article></body></html>")
        result = await research.read_page.ainvoke({"url": GIVE})
        assert result.startswith("[Give.do public NGO pages is an aggregator.")
        assert "village reading rooms" in result

    async def test_the_guidestar_search_api_returns_its_json(self, web):
        pages, _ = web
        url = ("https://guidestarindia.frappe.cloud/api/method/guidestar.api.npo_profile.npo_profile_search"
               "?keyword=Example+Valley+Trust&page_no=1")
        pages[url] = httpx.Response(200, json={"message": [{"npo_name": "Example Valley Trust", "city": "Northfield"}]})
        result = await research.read_page.ainvoke({"url": url})
        assert "aggregator" in result and "Example Valley Trust" in result and "Northfield" in result

    async def test_a_dossier_at_the_pinned_commit_is_read_as_prior_research(self, web):
        pages, _ = web
        url = REPO_ROOT + "ngos/example-valley-trust/profile.md"
        pages[url] = httpx.Response(200, headers={"content-type": "text/plain; charset=utf-8"},
                                    text="| PAN | TESTP0000X |\n| 80G | granted |\n")
        result = await research.read_page.ainvoke({"url": url})
        assert "prior_research" in result and "| 80G | granted |" in result

    async def test_a_directory_listing_is_compacted(self, web):
        pages, _ = web
        url = "https://api.github.com/repos/project-tech4dev/org-grant-intelligence/contents/ngos/example?ref=" + SHA
        pages[url] = httpx.Response(200, json=[
            {"name": "profile.md", "type": "file", "download_url": REPO_ROOT + "ngos/example/profile.md",
             "sha": "x" * 40, "size": 10, "_links": {"self": "https://api.github.com/x"}},
        ])
        result = await research.read_page.ainvoke({"url": url})
        assert f"profile.md · file · {REPO_ROOT}ngos/example/profile.md" in result
        assert "_links" not in result

    async def test_fetch_document_refuses_a_redirect_off_the_allowlist(self, web):
        pages, sent = web
        url = REPO_ROOT + "downloads/template.pdf"
        other = "https://raw.githubusercontent.com/someone-else/any-repo/main/template.pdf"
        pages[url] = httpx.Response(302, headers={"location": other})
        result = await research.fetch_document.ainvoke({"url": url})
        assert result.startswith("REFUSED:")
        assert other not in sent
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_source_access.py -q -k "BlockedPage or FetchTools"`
Expected: `AttributeError: module 'app.ingest.access' has no attribute 'blocked_page'`, then failures on redirects (followed), the JSON page ("No readable text"), and the banner.

- [ ] **Step 3: Add `blocked_page` and the reply to `access.py`**

Add `import re` to the imports. Append:

```python
# A page under this much readable text is a challenge, not content. A long page that merely embeds
# a reCAPTCHA in its contact form is a page and is read.
READABLE_FLOOR = 1_500
BLOCK_SCAN_CHARS = 50_000
_SIGN_IN_PATH = re.compile(r"/(?:login|log-in|signin|sign-in|sso|users/sign_in|account/login)(?:[/.?]|$)", re.I)
_CAPTCHA = re.compile(r"captcha|cf-challenge|cf_chl_|verify (?:that )?you are (?:a )?human|are you a robot", re.I)
_PASSWORD_FIELD = re.compile(r"<input[^>]+type\s*=\s*[\"']?password", re.I)


def blocked_page(status: int, url: str, html: str, *, readable_chars: int) -> str | None:
    """Why a response is a wall rather than an answer, or None. Pure.

    A wall is never "not found": a registry behind a CAPTCHA has said nothing about the
    registration, so what it would have confirmed is check_blocked (spec §2).
    """
    if status in (401, 407):
        return f"HTTP {status}, a sign-in demand"
    if status == 403:
        return "HTTP 403, access refused"
    if status == 429:
        return "HTTP 429, too many requests"
    if _SIGN_IN_PATH.search(urlparse(url).path):
        return "a sign-in page"
    if readable_chars < READABLE_FLOOR:
        head = html[:BLOCK_SCAN_CHARS]
        if _CAPTCHA.search(head):
            return "a CAPTCHA"
        if _PASSWORD_FIELD.search(head):
            return "a sign-in form"
    return None


def check_blocked_reply(url: str, reason: str) -> str:
    return (
        f"CHECK BLOCKED: {url} answered with {reason}, so nothing on it was read. This is not "
        f"'not found': a registration this page would have confirmed is status check_blocked, and "
        f"a person checks it by hand. Do not try another route to it."
    )
```

- [ ] **Step 4: Rework `research_tools.py`**

Change the imports to:

```python
from typing import Any

from app.ingest.access import blocked_page, check_blocked_reply, check_url, source_banner
```

Add, after `PAGE_HEADERS`:

```python
class _Stop(Exception):
    """Raised from the request hook: a redirect led somewhere this tool may not go."""

    def __init__(self, reply: str):
        super().__init__(reply)
        self.reply = reply


def _client(original: str, **kwargs: Any) -> httpx.AsyncClient:
    """A client that checks every redirect hop BEFORE it is requested.

    check_url saw only the first URL. With follow_redirects alone, a /discover/ page that
    redirects to /api/, or a pinned dossier that redirects to another repository, would be
    fetched before anyone looked. httpx calls request hooks once per request, redirects included.
    """
    first = httpx.URL(original)

    async def guard(request: httpx.Request) -> None:
        if request.url == first:
            return
        target = str(request.url)
        wall = blocked_page(200, target, "", readable_chars=READABLE_FLOOR)
        if wall:
            raise _Stop(check_blocked_reply(original, wall))
        refusal = await check_url(target)
        if refusal:
            raise _Stop(f"REFUSED: {original} redirected to {target}, which was not requested. {refusal}")

    return httpx.AsyncClient(follow_redirects=True, event_hooks={"request": [guard]}, **kwargs)


def _compact_json(text: str) -> str:
    """A directory listing as one line per entry; any other JSON as it came."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if isinstance(data, list) and data and all(isinstance(e, dict) and "name" in e and "type" in e for e in data):
        return "\n".join(f"{e['name']} · {e['type']} · {e.get('download_url') or e.get('path', '')}" for e in data)
    return text
```

Add `READABLE_FLOOR` to the `app.ingest.access` import.

Replace the body of `read_page` (keep its decorator and signature) with the following. Append this paragraph to its docstring: `A sign-in page, a CAPTCHA or a 401/403/429 comes back as CHECK BLOCKED: nothing was read, and a registration it would have confirmed is check_blocked, never not_found.`

```python
    refusal = await check_url(url)
    if refusal:
        return f"REFUSED: {refusal}"
    try:
        async with _client(url, timeout=TIMEOUT_SECONDS, headers=PAGE_HEADERS) as client:
            response = await client.get(url)
            response.raise_for_status()
    except _Stop as stop:
        return stop.reply
    except httpx.HTTPStatusError as exc:
        wall = blocked_page(exc.response.status_code, str(exc.response.url), "", readable_chars=0)
        if wall:
            return check_blocked_reply(url, wall)
        return f"ERROR: {url} returned HTTP {exc.response.status_code}. Nothing was read."
    except httpx.HTTPError as exc:
        return f"ERROR: fetching {url} failed ({type(exc).__name__}: {exc})."

    content_type = response.headers.get("content-type", "").lower()
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        return (
            f"{url} is a PDF ({len(response.content):,} bytes). Use fetch_document to save it, "
            f"then read_document_pages to read it."
        )
    if "json" in content_type:
        # The GuideStar search API and GitHub's directory listings. trafilatura extracts nothing
        # from JSON, which would read as an empty page.
        text = _compact_json(response.text)
    elif content_type.startswith("text/plain") or "markdown" in content_type:
        text = response.text                 # a raw dossier file is markdown served as text/plain
    else:
        text = trafilatura.extract(response.text, url=url) or ""
        wall = blocked_page(response.status_code, str(response.url), response.text,
                            readable_chars=len(text.strip()))
        if wall:
            return check_blocked_reply(url, wall)
    if not text.strip():
        return f"No readable text could be extracted from {url}."
    if len(text) > MAX_CONTENT_CHARS:
        text = text[:MAX_CONTENT_CHARS] + f"\n\n[truncated at {MAX_CONTENT_CHARS} characters]"
    return source_banner(str(response.url)) + text
```

In `fetch_document`, replace its `try:` … `except httpx.HTTPError` block's client construction and exceptions so the block reads:

```python
    try:
        async with _client(url, timeout=120, headers=PAGE_HEADERS) as client, \
                client.stream("GET", url) as response:
            response.raise_for_status()
            # … the existing body of the with-block, unchanged …
    except _Stop as stop:
        return stop.reply
    except httpx.HTTPStatusError as exc:
        wall = blocked_page(exc.response.status_code, str(exc.response.url), "", readable_chars=0)
        if wall:
            return check_blocked_reply(url, wall)
        return f"ERROR: download of {url} failed (HTTP {exc.response.status_code})."
    except httpx.HTTPError as exc:
        return f"ERROR: download of {url} failed ({type(exc).__name__}: {exc})."
```

`tests/test_storage.py` replaces `httpx.AsyncClient` with `lambda **kw: _FakeClient(…)`. `_client` passes `event_hooks` and `follow_redirects` through `**kw`, so those tests keep working unchanged.

- [ ] **Step 5: Show `CHECK BLOCKED` in the trace**

In `frontend/features/ingest/lib/toolLabels.ts`, inside `stepNote`, add this as the first check after `const first = …`:

```ts
  if (first.startsWith("CHECK BLOCKED:")) return reason(first.slice("CHECK BLOCKED:".length));
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest tests/test_source_access.py tests/test_storage.py -q && ruff check .`
Expected: all pass, and ruff is clean.

Run: `cd frontend && npm ci && npm run lint && npm run build`
Expected: lint clean, and the build succeeds.

- [ ] **Step 7: Commit**

```bash
git add backend/app/ingest/access.py backend/app/ingest/tools/research_tools.py frontend/features/ingest/lib/toolLabels.ts backend/tests/test_source_access.py
git commit -m "feat(ingest): check every redirect hop; a wall is check_blocked, not empty

read_page and fetch_document run check_url on each redirect before requesting
it. A 401/403/429, a sign-in page or a short CAPTCHA page returns CHECK
BLOCKED. JSON and plain-text answers (the GuideStar API, pinned dossiers) are
read as text, under a banner saying how to label them.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Source guards at save and at promote

**Files:**
- Create: `backend/app/ingest/source_guards.py`
- Modify: `backend/app/ingest/research_records.py`, `backend/app/ingest/promote.py`
- Test: `backend/tests/test_source_guards.py` (create)

**Interfaces:**

```python
TIER_FIELDS: frozenset[str]                                         # {"source_type", "evidence_tier"}
def labelled_by(url: str) -> tuple[str, str] | None                # (required source_type, source name)
def problems(concept: str, finding: dict, fields: frozenset[str], *, at: Literal["save", "promote"]) -> list[str]
def check_research(findings: list[FindingBase]) -> list[str]        # at save
def hold_at_promote(findings: list[dict]) -> tuple[list[dict], list[str]]
```

Two moments, two behaviours:
- **At save**, a finding whose model *can* carry the label but carries the wrong one is refused. The model fixes it and saves again.
- **At promote**, the same check runs again, because a row saved before this PR, or by an older shape, never went through it. It also holds any finding from a labelled source whose concept has no tier columns, such as a funder-side `partner` read off a dossier. That finding stays research until a primary source confirms it. The research record keeps every value as found (spec §1).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_source_guards.py`:

```python
"""Where a fact came from decides what it may claim. Synthetic organisations only."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ingest import promote, source_guards
from app.ingest.research_records import EntityResearch

SHA = "414cd6968765bcfff758632797dcbb8d00363ab2"
GIVE = "https://give.do/discover/ABCD/example-valley-trust/"
DOSSIER = f"https://raw.githubusercontent.com/project-tech4dev/org-grant-intelligence/{SHA}/ngos/example/profile.md"
OWN = "https://example-valley-trust.example/docs/12a-order.pdf"
DARPAN = "https://ngodarpan.gov.in/index.php/search/"


def identifier(**kw) -> dict:
    return {
        "concept": "org_identifier", "id_type": "80g", "id_value": "TEST-80G-0001", "status": "registered",
        "evidence": "The page lists the trust as holding an 80G registration.", "source_url": OWN,
        "confidence": "medium", "source_type": "org_document", "evidence_tier": "evidenced", **kw,
    }


def partner(**kw) -> dict:
    return {
        "concept": "partner", "fiscal_year": "FY2023-24", "partner_name": "Example Valley Trust",
        "evidence": "The profile names the trust's funders for the year, with amounts.",
        "source_url": DOSSIER, "confidence": "low", **kw,
    }


def research(*findings: dict) -> dict:
    return {"entity_name": "Example Valley Trust", "entity_kind": "org", "status": "complete",
            "summary": "A synthetic organisation used only in these tests.", "findings": list(findings)}


FIELDS = frozenset({"source_type", "evidence_tier", "status", "id_type"})


class TestLabels:
    def test_an_aggregator_finding_must_be_claimed(self):
        wrong = source_guards.problems("org_identifier", identifier(source_url=GIVE), FIELDS, at="save")
        assert wrong and "source_type='aggregator'" in wrong[0] and "evidence_tier='claimed'" in wrong[0]
        right = identifier(source_url=GIVE, source_type="aggregator", evidence_tier="claimed")
        assert source_guards.problems("org_identifier", right, FIELDS, at="save") == []

    def test_any_give_do_url_counts_as_the_aggregator(self):
        assert source_guards.labelled_by("https://give.do/fundraisers/x")[0] == "aggregator"

    def test_a_dossier_finding_must_be_prior_research_and_claimed(self):
        wrong = source_guards.problems("org_identifier", identifier(source_url=DOSSIER), FIELDS, at="save")
        assert wrong and "source_type='prior_research'" in wrong[0]
        right = identifier(source_url=DOSSIER, source_type="prior_research", evidence_tier="claimed")
        assert source_guards.problems("org_identifier", right, FIELDS, at="save") == []

    def test_a_dossier_at_another_commit_is_not_prior_research(self):
        assert source_guards.labelled_by(DOSSIER.replace(SHA, "main")) is None

    def test_an_own_document_is_left_to_the_researcher(self):
        assert source_guards.problems("org_identifier", identifier(), FIELDS, at="save") == []

    def test_not_found_from_an_unreadable_registry_is_refused(self):
        found = identifier(source_url=DARPAN, status="not_found", id_type="darpan", id_value=None,
                           source_type="registry", evidence_tier="claimed")
        wrong = source_guards.problems("org_identifier", found, FIELDS, at="save")
        assert wrong and "'check_blocked', not 'not_found'" in wrong[0]

    def test_a_concept_without_tier_fields_passes_save_and_is_held_at_promote(self):
        no_tier = frozenset({"partner_name"})
        assert source_guards.problems("partner", partner(), no_tier, at="save") == []
        held = source_guards.problems("partner", partner(), no_tier, at="promote")
        assert held and "stays research" in held[0]


class TestAtSave:
    def test_save_research_refuses_an_aggregator_value_marked_evidenced(self):
        with pytest.raises(ValidationError, match="evidence_tier='claimed'"):
            EntityResearch.model_validate(research(identifier(source_url=GIVE, source_type="aggregator")))

    def test_a_correctly_labelled_payload_saves(self):
        payload = research(identifier(source_url=GIVE, source_type="aggregator", evidence_tier="claimed"))
        assert EntityResearch.model_validate(payload).findings


class TestAtPromote:
    async def test_promotion_holds_an_aggregator_finding_its_table_cannot_mark_claimed(self, monkeypatch):
        seen: list[list[dict]] = []

        async def fake_org(conn, row, findings, report):
            seen.append(findings)

        monkeypatch.setattr(promote, "_promote_org", fake_org)
        good = identifier()
        mislabelled = identifier(source_url=GIVE)                 # saved before the guard existed
        row = {"slug": "example-valley-trust", "entity_kind": "org", "schema_version": promote.SCHEMA_VERSION,
               "findings": [good, mislabelled]}
        report = await promote.promote(None, row)
        assert seen == [[good]]
        assert any("aggregator" in h for h in report["held"])

    def test_a_dossier_partner_is_held_at_promote_not_at_save(self):
        kept, held = source_guards.hold_at_promote([partner()])
        assert kept == [] and held and "stays research" in held[0]
```

If (e) gave `PartnerFinding` the tier fields, the last test's `partner()` must carry `source_type='prior_research'` and `evidence_tier='claimed'`, and it then passes through `kept`. Rewrite the assertion to `kept == [partner(...)]` and `held == []` to match. Task 1, Step 1 shows which applies (`grep -n "class PartnerFinding" -A15 app/ingest/research_records.py`).

The `partner` dict above uses (b)/(e)'s `PartnerFinding` field names. If `partner_name` is not its name field, copy the required fields from `PartnerFinding.model_fields` (Task 1 verified the class exists).

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_source_guards.py -q`
Expected: `ModuleNotFoundError: No module named 'app.ingest.source_guards'`.

- [ ] **Step 3: Write `source_guards.py`**

Create `backend/app/ingest/source_guards.py`:

```python
"""Where a fact came from decides what it may claim. Pure: no pool, no settings.

Three rules a prompt states and this module enforces, because a prompt can be skimmed:
  - an aggregator's value is claimed, always (spec C8);
  - a value from the team's earlier research is prior_research and claimed until a primary
    source is re-read (spec C14);
  - a registry Sangam cannot read cannot have shown a registration missing, so a not_found from
    one is check_blocked (spec §2).

At save a mislabelled finding is refused, so the model fixes it. At promote the same check runs
again (older rows never met it), and a labelled finding whose table cannot mark a value claimed
is held: it stays research, as found.
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

from app.ingest.sources import AccessRule, rule_for_url, sources_on_host

TIER_FIELDS: frozenset[str] = frozenset({"source_type", "evidence_tier"})
_UNREADABLE: frozenset[AccessRule] = frozenset({AccessRule.MANUAL_ONLY, AccessRule.NO_SCRAPING})


def labelled_by(url: str) -> tuple[str, str] | None:
    """The source_type a finding citing this URL must carry, and the source's name; else None.

    Prior research is decided by path (only the pinned commit is the repo source). An aggregator
    is decided by host: any page on it is the aggregator's account, whichever entry governs it.
    """
    found = rule_for_url(url)
    if found and found[0] is AccessRule.INTERNAL_RESEARCH:
        return "prior_research", found[1].name
    for source in sources_on_host(urlparse(url).hostname or ""):
        if source.access_rule is AccessRule.MANUAL_AGGREGATOR:
            return "aggregator", source.name
    return None


def problems(
    concept: str, finding: dict[str, Any], fields: frozenset[str], *, at: Literal["save", "promote"]
) -> list[str]:
    url = str(finding.get("source_url") or "")
    out: list[str] = []
    label = labelled_by(url)
    if label is not None:
        source_type, name = label
        if TIER_FIELDS <= fields:
            if finding.get("source_type") != source_type or finding.get("evidence_tier") != "claimed":
                out.append(
                    f"{concept} from {name}: set source_type='{source_type}' and evidence_tier='claimed'. "
                    f"A value from {name} is claimed until a primary source shows it."
                )
        elif at == "promote":
            out.append(
                f"{concept} from {name}: a {concept} row cannot be marked claimed, so it stays research "
                f"until the organisation's own document or a funder's page confirms it."
            )
    if concept == "org_identifier" and finding.get("status") == "not_found":
        found = rule_for_url(url)
        if found is not None and found[0] in _UNREADABLE:
            out.append(
                f"org_identifier {finding.get('id_type')} from {found[1].name}: Sangam cannot read that "
                f"registry, so it cannot have shown the registration missing. Record status "
                f"'check_blocked', not 'not_found', and say a person must check it by hand."
            )
    return out


def check_research(findings: list[Any]) -> list[str]:
    """Every problem in a payload being saved. Findings are the pydantic models."""
    out: list[str] = []
    for f in findings:
        out += problems(f.concept, f.model_dump(), frozenset(type(f).model_fields), at="save")
    return out


def hold_at_promote(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Findings that may be promoted, and a held reason for each one that may not."""
    from app.ingest.research_records import FINDING_MODELS   # research_records imports this module

    kept: list[dict[str, Any]] = []
    held: list[str] = []
    for f in findings:
        model = FINDING_MODELS.get(str(f.get("concept")))
        fields = frozenset(model.model_fields) if model else frozenset()
        why = problems(str(f.get("concept")), f, fields, at="promote")
        if why:
            held.extend(why)
        else:
            kept.append(f)
    return kept, held
```

- [ ] **Step 4: Wire it in**

In `backend/app/ingest/research_records.py`, add to `EntityResearch` after `_complete_means_something_was_found`:

```python
    @model_validator(mode="after")
    def _sources_are_labelled_honestly(self) -> EntityResearch:
        # Imported here: source_guards reads FINDING_MODELS from this module at promote time.
        from app.ingest import source_guards

        wrong = source_guards.check_research(self.findings)
        if wrong:
            raise ValueError("; ".join(wrong))
        return self
```

In `backend/app/ingest/promote.py`, add `source_guards` to the `from app.ingest import …` line. In `promote()`, directly after (c)'s two lines

```python
    findings, unmarked = staff_sources.hold_unmarked(findings)
    report["held"].extend(unmarked)
```

insert:

```python
    findings, mislabelled = source_guards.hold_at_promote(findings)
    report["held"].extend(mislabelled)
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && pytest tests/test_source_guards.py tests/test_ingest.py tests/test_staff_sources.py -q && ruff check .`
Expected: all pass. No existing test cites give.do, the research repo or a held registry with `not_found`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingest/source_guards.py backend/app/ingest/research_records.py backend/app/ingest/promote.py backend/tests/test_source_guards.py
git commit -m "feat(ingest): aggregator and prior-research values are claimed, in code

save_research refuses a finding from an aggregator or the pinned research repo
that is not labelled claimed with its source_type, and a not_found from a
registry Sangam cannot read. Promotion re-checks and holds what its table cannot
mark claimed.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Manual checks — validation and the write

**Files:**
- Create: `backend/app/ingest/manual_checks.py`
- Test: `backend/tests/test_manual_checks.py` (create)

The tool that wraps this module, and its registration, are Task 7. That way this task ends green: a tool defined here but not registered would fail `test_every_tool_defined_is_also_registered`.

**Interfaces:**

```python
# manual_checks.py
ID_TYPES: tuple[str, ...]; STATUSES: tuple[str, ...]; NOTE_MAX = 500
def refusal(*, id_type: str, status: str, document_id: Any, note: str, user_id: UUID | None) -> str | None
async def _is_staff(conn, user_id: UUID) -> bool
async def _orgs(conn, org: str) -> list[dict]
async def _document(conn, document_id: int) -> dict | None
async def _identifiers(conn, org_id: int, id_type: str) -> list[dict]
async def _write(conn, *, identifier_id: int | None, org_id: int, id_type: str, status: str,
                 document_id: int, user_id: UUID, note: str) -> dict
async def record(pool, *, org: str, id_type: str, status: str, document_id: Any, note: str,
                 user_id: UUID | None) -> str
```

Decisions this task makes:
- **Any document of that organisation counts as evidence.** The Doc Vault UI sets no `doc_type` and uploads land as `vault_upload`, so requiring `manual_check_evidence` would make the tool unusable. What is required is that the document exists, belongs to that organisation (`documents.org_id`), and is an uploaded file (`storage_path` set).
- **A check is dated, so a later one replaces an earlier one, even of equal rank.** The reply states the status it replaced, and the identifier's `notes` keep a dated line per check.
- **One identifier row per (org, id_type).** If two current rows exist, the tool refuses rather than guess between them. If none exists, it opens one with no number (`id_value IS NULL`), which (d)'s `org_identifiers_open_uq` permits.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_manual_checks.py`:

```python
"""A registry check a person made by hand. Unit tests patch the lookups; one class is integration."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.ingest import manual_checks

STAFF = UUID("00000000-0000-0000-0000-000000000001")
ORG = {"id": 7, "name": "Example Valley Trust", "slug": "example-valley-trust"}
DOC = {"id": 42, "org_id": 7, "title": "Registry screenshot", "doc_type": "vault_upload",
       "storage_path": "vault/7/registry.png"}
CURRENT = {"id": 3, "id_value": "TEST-FCRA-0001", "status": "registered", "check_method": "document",
           "source_type": "org_document"}


class _Conn:
    @asynccontextmanager
    async def transaction(self):
        yield self


class _Pool:
    @asynccontextmanager
    async def connection(self):
        yield _Conn()


@pytest.fixture
def world(monkeypatch):
    state = {"staff": True, "orgs": [ORG], "doc": DOC, "rows": [CURRENT], "writes": []}

    async def is_staff(conn, user_id):
        return state["staff"]

    async def orgs(conn, org):
        return state["orgs"]

    async def document(conn, document_id):
        return state["doc"] if state["doc"] and state["doc"]["id"] == document_id else None

    async def identifiers(conn, org_id, id_type):
        return state["rows"]

    async def write(conn, **kw):
        state["writes"].append(kw)
        return {"id": kw["identifier_id"] or 99, "id_value": "TEST-FCRA-0001" if kw["identifier_id"] else None,
                "checked_at": datetime(2026, 10, 7, tzinfo=UTC)}

    for name, fn in [("_is_staff", is_staff), ("_orgs", orgs), ("_document", document),
                     ("_identifiers", identifiers), ("_write", write)]:
        monkeypatch.setattr(manual_checks, name, fn)
    return state


async def check(**kw):
    args = {"org": "example-valley-trust", "id_type": "fcra", "status": "check_blocked", "document_id": 42,
            "note": "portal did not load from two networks", "user_id": STAFF, **kw}
    return await manual_checks.record(_Pool(), **args)


class TestRecordRegistryCheck:
    async def test_a_check_updates_the_current_identifier_and_cites_its_evidence(self, world):
        reply = await check()
        assert "[org:7]" in reply and "[document:42]" in reply and "check_blocked" in reply
        assert "replaces status 'registered'" in reply
        (write,) = world["writes"]
        assert (write["identifier_id"], write["status"], write["document_id"], write["user_id"]) == (
            3, "check_blocked", 42, STAFF)

    async def test_a_check_with_no_identifier_on_file_opens_one(self, world):
        world["rows"] = []
        reply = await check(status="applied", id_type="80g")
        assert world["writes"][0]["identifier_id"] is None and "no number on file" in reply

    @pytest.mark.parametrize("document_id", [0, -1, None, "42"])
    async def test_a_check_without_evidence_writes_nothing(self, world, document_id):
        reply = await check(document_id=document_id)
        assert reply.startswith("REFUSED:") and "evidence" in reply and world["writes"] == []

    async def test_a_document_that_does_not_exist_is_refused(self, world):
        reply = await check(document_id=43)
        assert reply.startswith("REFUSED:") and "does not exist" in reply and world["writes"] == []

    async def test_a_document_of_another_org_is_refused(self, world):
        world["doc"] = {**DOC, "org_id": 8}
        reply = await check()
        assert reply.startswith("REFUSED:") and "[org:8]" in reply and world["writes"] == []

    async def test_a_document_with_no_uploaded_file_is_refused(self, world):
        world["doc"] = {**DOC, "storage_path": None}
        assert (await check()).startswith("REFUSED:") and world["writes"] == []

    async def test_no_signed_in_user_writes_nothing(self, world):
        reply = await check(user_id=None)
        assert reply.startswith("REFUSED:") and "staff member" in reply and world["writes"] == []

    async def test_a_non_staff_user_writes_nothing(self, world):
        world["staff"] = False
        assert (await check()).startswith("REFUSED:") and world["writes"] == []

    @pytest.mark.parametrize(("field", "value"), [("status", "valid"), ("id_type", "gst")])
    async def test_an_unknown_status_or_type_is_refused(self, world, field, value):
        assert (await check(**{field: value})).startswith("REFUSED:") and world["writes"] == []

    async def test_two_current_identifiers_are_not_guessed_between(self, world):
        world["rows"] = [CURRENT, {**CURRENT, "id": 4, "id_value": "TEST-FCRA-0002"}]
        reply = await check()
        assert reply.startswith("REFUSED:") and "TEST-FCRA-0002" in reply and world["writes"] == []

    async def test_an_ambiguous_org_is_refused(self, world):
        world["orgs"] = [ORG, {**ORG, "id": 8, "slug": "example-valley-trust-2"}]
        assert (await check(org="Example Valley Trust")).startswith("REFUSED:") and world["writes"] == []


DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")


@pytest.mark.integration
class TestTheWriteAgainstTheSchema:
    @pytest.fixture
    async def conn(self):
        import psycopg
        from psycopg.rows import dict_row

        try:
            conn = await psycopg.AsyncConnection.connect(DSN, row_factory=dict_row, connect_timeout=3)
        except psycopg.OperationalError:
            pytest.skip("compose Postgres not reachable on localhost:5433")
        try:
            yield conn
        finally:
            await conn.rollback()
            await conn.close()

    async def test_every_status_writes_and_the_row_carries_its_checker(self, conn):
        org = await (await conn.execute(
            "INSERT INTO orgs (slug, name) VALUES ('test-manual-check', 'Example Valley Trust') RETURNING id"
        )).fetchone()
        doc = await (await conn.execute(
            "INSERT INTO documents (org_id, title, doc_type, storage_path, is_public) "
            "VALUES (%s, 'Registry screenshot', 'vault_upload', 'vault/test/registry.png', false) RETURNING id",
            (org["id"],),
        )).fetchone()
        assert await manual_checks._identifiers(conn, org["id"], "fcra") == []
        first = await manual_checks._write(conn, identifier_id=None, org_id=org["id"], id_type="fcra",
                                           status="check_blocked", document_id=doc["id"], user_id=STAFF,
                                           note="portal unreachable")
        for status in manual_checks.STATUSES:
            await manual_checks._write(conn, identifier_id=first["id"], org_id=org["id"], id_type="fcra",
                                       status=status, document_id=doc["id"], user_id=STAFF, note=status)
        row = await (await conn.execute(
            "SELECT id_value, status, check_method, checked_by, evidence_document_id, source_type, evidence, notes "
            "FROM org_identifiers WHERE id = %s", (first["id"],),
        )).fetchone()
        assert row["id_value"] is None and row["status"] == manual_checks.STATUSES[-1]
        assert (row["check_method"], row["checked_by"], row["evidence_document_id"]) == (
            "manual_check", STAFF, doc["id"])
        assert (row["source_type"], row["evidence"]) == ("manual_check", "evidenced")
        assert row["notes"].count("manual check ") == len(manual_checks.STATUSES) + 1
        assert [r["id"] for r in await manual_checks._identifiers(conn, org["id"], "fcra")] == [first["id"]]
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_manual_checks.py -q -m "not integration"`
Expected: `ModuleNotFoundError: No module named 'app.ingest.manual_checks'`.

- [ ] **Step 3: Write `manual_checks.py`**

Create `backend/app/ingest/manual_checks.py`:

```python
"""A registry check a person made by hand (spec C9), and the one place it is written.

For registries no machine may read: a CAPTCHA, a login or a network filter in the way. A staff
member looks the registration up, uploads what they saw to the organisation's Doc Vault, and the
status is stored on the identifier row with that document. Precedence puts a manual check level
with a registry read; a check is dated, so a later one replaces an earlier one and says so.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from uuid import UUID

ID_TYPES: tuple[str, ...] = ("pan", "12a", "80g", "fcra", "csr1", "darpan", "cin", "reg_no")
STATUSES: tuple[str, ...] = (
    "applied", "provisional", "registered", "expired", "suspended", "cancelled",
    "surrendered", "not_available", "not_found", "check_blocked",
)
NOTE_MAX = 500
_ORG_ID = re.compile(r"\[?org:(\d+)\]?|(\d+)")


def refusal(*, id_type: str, status: str, document_id: Any, note: str, user_id: UUID | None) -> str | None:
    if user_id is None:
        return ("REFUSED: no signed-in staff member is attached to this conversation, so nobody can be "
                "recorded as having made the check. Nothing was written.")
    if id_type not in ID_TYPES:
        return f"REFUSED: id_type must be one of {', '.join(ID_TYPES)}, not {id_type!r}. Nothing was written."
    if status not in STATUSES:
        return f"REFUSED: status must be one of {', '.join(STATUSES)}, not {status!r}. Nothing was written."
    if not isinstance(document_id, int) or isinstance(document_id, bool) or document_id <= 0:
        return ("REFUSED: a manual check is recorded only with its evidence. Ask the staff member to upload "
                "the screenshot or certificate to the organisation's Doc Vault, then pass that document's id. "
                "Nothing was written.")
    if len(note) > NOTE_MAX:
        return f"REFUSED: keep the note under {NOTE_MAX} characters. Nothing was written."
    return None


async def _is_staff(conn: Any, user_id: UUID) -> bool:
    row = await (await conn.execute("SELECT is_staff FROM users WHERE id = %s", (user_id,))).fetchone()
    return bool(row and row["is_staff"])


async def _orgs(conn: Any, org: str) -> list[dict]:
    key = org.strip()
    m = _ORG_ID.fullmatch(key)
    if m:
        sql, params = "SELECT id, name, slug FROM orgs WHERE id = %s", (int(m.group(1) or m.group(2)),)
    else:
        sql, params = ("SELECT id, name, slug FROM orgs WHERE slug = %s OR lower(name) = lower(%s) "
                       "ORDER BY id LIMIT 5", (key, key))
    return list(await (await conn.execute(sql, params)).fetchall())


async def _document(conn: Any, document_id: int) -> dict | None:
    return await (await conn.execute(
        "SELECT id, org_id, title, doc_type, storage_path FROM documents WHERE id = %s", (document_id,)
    )).fetchone()


async def _identifiers(conn: Any, org_id: int, id_type: str) -> list[dict]:
    return list(await (await conn.execute(
        "SELECT id, id_value, status, check_method, source_type FROM org_identifiers "
        "WHERE org_id = %s AND id_type = %s AND is_current ORDER BY id FOR UPDATE",
        (org_id, id_type),
    )).fetchall())


async def _write(
    conn: Any, *, identifier_id: int | None, org_id: int, id_type: str, status: str,
    document_id: int, user_id: UUID, note: str,
) -> dict:
    line = f"manual check {date.today().isoformat()}: {note or 'no note'}"
    if identifier_id is None:
        sql = (
            "INSERT INTO org_identifiers (org_id, id_type, id_value, status, checked_at, checked_by, "
            "check_method, evidence_document_id, source_type, evidence, notes) "
            "VALUES (%s, %s, NULL, %s, now(), %s, 'manual_check', %s, 'manual_check', 'evidenced', %s) "
            "RETURNING id, id_value, checked_at"
        )
        params: tuple = (org_id, id_type, status, user_id, document_id, line)
    else:
        sql = (
            "UPDATE org_identifiers SET status = %s, checked_at = now(), checked_by = %s, "
            "check_method = 'manual_check', evidence_document_id = %s, source_type = 'manual_check', "
            "evidence = 'evidenced', notes = concat_ws(E'\\n', notes, %s) "
            "WHERE id = %s RETURNING id, id_value, checked_at"
        )
        params = (status, user_id, document_id, line, identifier_id)
    return await (await conn.execute(sql, params)).fetchone()


async def record(
    pool: Any, *, org: str, id_type: str, status: str, document_id: Any, note: str, user_id: UUID | None,
) -> str:
    note = " ".join((note or "").split())
    id_type, status = (id_type or "").strip().lower(), (status or "").strip().lower()
    why = refusal(id_type=id_type, status=status, document_id=document_id, note=note, user_id=user_id)
    if why:
        return why
    async with pool.connection() as conn, conn.transaction():
        if not await _is_staff(conn, user_id):
            return "REFUSED: only a staff member's check is recorded, and this conversation is not staff's."
        orgs = await _orgs(conn, org)
        if not orgs:
            return f"REFUSED: no organisation in the catalog matches {org!r}. Pass its slug or its [org:N] id."
        if len(orgs) > 1:
            named = ", ".join(f"{o['name']} [org:{o['id']}] ({o['slug']})" for o in orgs)
            return f"REFUSED: {org!r} names more than one organisation: {named}. Pass the slug or [org:N]."
        target = orgs[0]
        doc = await _document(conn, document_id)
        if doc is None:
            return f"REFUSED: document {document_id} does not exist. Nothing was written."
        if doc["org_id"] != target["id"]:
            owner = "no organisation" if doc["org_id"] is None else f"[org:{doc['org_id']}]"
            return (f"REFUSED: document {document_id} belongs to {owner}, not {target['name']} "
                    f"[org:{target['id']}]. Evidence is uploaded to the checked organisation's Doc Vault.")
        if not doc["storage_path"]:
            return f"REFUSED: document {document_id} has no uploaded file, so it shows nothing. Nothing was written."
        rows = await _identifiers(conn, target["id"], id_type)
        if len(rows) > 1:
            listed = ", ".join(f"row {r['id']} ({r['id_value'] or 'no number'})" for r in rows)
            return (f"REFUSED: [org:{target['id']}] holds {len(rows)} current {id_type} identifiers: {listed}. "
                    f"A person decides which is current before a check is recorded. Nothing was written.")
        prior = rows[0] if rows else None
        written = await _write(
            conn, identifier_id=prior["id"] if prior else None, org_id=target["id"], id_type=id_type,
            status=status, document_id=doc["id"], user_id=user_id, note=note,
        )
    replaced = (
        f" It replaces status {prior['status']!r} "
        f"(from {prior['check_method'] or prior['source_type'] or 'an unrecorded method'})."
        if prior and prior["status"] != status else ""
    )
    return (
        f"Recorded a manual check for {target['name']} [org:{target['id']}]: {id_type} "
        f"({written['id_value'] or 'no number on file'}) is {status}, checked "
        f"{written['checked_at']:%Y-%m-%d} by a staff member, evidence [document:{doc['id']}] "
        f"{doc['title'] or 'untitled'}. Identifier row {written['id']}.{replaced}"
    )
```

- [ ] **Step 4: Run the tests**

```bash
cd backend && pytest tests/test_manual_checks.py tests/test_ingest.py -q -m "not integration"
cd backend && pytest tests/test_manual_checks.py -q -m integration     # needs make up && make migrate with (d)
cd backend && ruff check .
```

Expected: the unit tests pass, `test_ingest.py` included (no tool is defined yet). The integration class passes, or skips when `:5433` is down. ruff is clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingest/manual_checks.py backend/tests/test_manual_checks.py
git commit -m "feat(ingest): manual registry checks, stored with their evidence

The checker must be a signed-in staff member. The evidence must be an uploaded
document of the checked organisation. One current identifier is updated, or an
open one inserted; two are never guessed between. The reply cites [org:N] and
[document:N].

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `record_registry_check` — the tool, on the supervisor, named and labelled

**Files:**
- Create: `backend/app/ingest/tools/registry_check_tools.py`
- Modify: `backend/app/ingest/agent.py`, `backend/app/ingest/instructions.md`
- Modify: `frontend/features/ingest/lib/toolLabels.ts`
- Test: `backend/tests/test_manual_checks.py`, `backend/tests/test_harness.py`, `backend/tests/test_ingest.py`

**Interfaces:**

```python
@tool async def record_registry_check(org: str, id_type: str, status: str, evidence_document_id: int, note: str = "") -> str
```

`TOOLS` gains it. Neither subagent gets it.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_manual_checks.py`, add these two imports:

```python
from app.core.security import chat_user_id
from app.ingest.tools import registry_check_tools
```

Then add this class after `TestRecordRegistryCheck`:

```python
class TestTheTool:
    def test_the_checker_is_never_an_argument(self):
        assert set(registry_check_tools.record_registry_check.args) == {
            "org", "id_type", "status", "evidence_document_id", "note"}

    async def test_the_checker_comes_from_the_conversation(self, monkeypatch):
        seen = {}

        async def record(pool, **kw):
            seen.update(kw)
            return "ok"

        monkeypatch.setattr(registry_check_tools.manual_checks, "record", record)
        monkeypatch.setattr(registry_check_tools, "get_pool", lambda: object())
        token = chat_user_id.set(STAFF)
        try:
            await registry_check_tools.record_registry_check.ainvoke(
                {"org": "example-valley-trust", "id_type": "pan", "status": "registered",
                 "evidence_document_id": 42})
        finally:
            chat_user_id.reset(token)
        assert seen["user_id"] == STAFF

    async def test_the_tool_never_raises(self, monkeypatch):
        async def boom(pool, **kw):
            raise RuntimeError("database went away")

        monkeypatch.setattr(registry_check_tools.manual_checks, "record", boom)
        monkeypatch.setattr(registry_check_tools, "get_pool", lambda: object())
        reply = await registry_check_tools.record_registry_check.ainvoke(
            {"org": "x", "id_type": "pan", "status": "registered", "evidence_document_id": 1})
        assert reply.startswith("record_registry_check failed: RuntimeError")
```

Append to `backend/tests/test_harness.py`:

```python
class TestTheManualCheckIsTheSupervisors:
    """A staff member talks to the supervisor; the researcher reads untrusted pages."""

    def test_on_the_supervisor(self):
        from app.ingest.agent import TOOLS

        assert "record_registry_check" in {t.name for t in TOOLS}

    def test_on_neither_subagent(self, subagents):
        for name, tools in subagents.items():
            assert "record_registry_check" not in tools, name
```

Append to `TestIngestAgentIsSelfDescribing` in `backend/tests/test_ingest.py`:

```python
    def test_the_instructions_say_who_may_ask_for_a_manual_check(self):
        from app.ingest.agent import INSTRUCTIONS

        section = INSTRUCTIONS.split("## Registrations: a status, and who checked", 1)[1].split("\n## ", 1)[0]
        for phrase in ("`applied` is not `registered`", "check_blocked", "never `not_found`",
                       "record_registry_check", "evidence", "`claimed`", "prior_research"):
            assert phrase in section, phrase
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_manual_checks.py tests/test_harness.py tests/test_ingest.py -q -m "not integration" -k "TheTool or ManualCheck or manual_check"`
Expected: `ImportError: cannot import name 'registry_check_tools'`. Once the tool file exists, `test_on_the_supervisor` fails, and the instructions test raises `IndexError`.

- [ ] **Step 3: Write the tool and register it**

Create `backend/app/ingest/tools/registry_check_tools.py`:

```python
"""Registry checks a machine cannot make, recorded for the staff member who made them (spec C9).

The supervisor's, alone: it is the agent the staff member is talking to. The researcher reads
untrusted pages, and the catalog-writer only moves saved research, so neither may write a check.
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from app.core.security import chat_user_id
from app.db.pool import get_pool
from app.ingest import manual_checks

logger = logging.getLogger(__name__)


@tool
async def record_registry_check(
    org: str, id_type: str, status: str, evidence_document_id: int, note: str = ""
) -> str:
    """Record a registry check a staff member made by hand, with the document that shows it.

    Use this only when the staff member tells you what they found and has uploaded the evidence
    (a screenshot, a certificate, a saved page) to the organisation's Doc Vault. Never record a
    check from your own reading or a researcher's: research is not a check.

    Args:
        org: the organisation's slug, or its id from [org:N].
        id_type: pan, 12a, 80g, fcra, csr1, darpan, cin or reg_no.
        status: registered, applied, provisional, expired, suspended, cancelled, surrendered,
            not_available, not_found (the registry was read and does not list it), or
            check_blocked (it could not be read even by hand). Applied is not registered.
        evidence_document_id: the uploaded document's id. Required: no document, no record.
        note: what was checked, where and how, in the staff member's words.
    """
    try:
        return await manual_checks.record(
            get_pool(), org=org, id_type=id_type, status=status, document_id=evidence_document_id,
            note=note, user_id=chat_user_id.get(),
        )
    except Exception as exc:  # noqa: BLE001 - a tool never raises into the agent
        logger.exception("record_registry_check failed")
        return f"record_registry_check failed: {type(exc).__name__}: {exc}"
```

Then register it.

In `backend/app/ingest/agent.py`, add the import:

```python
from app.ingest.tools.registry_check_tools import record_registry_check
```

In the comment above `TOOLS`, replace the sentence `It researches nothing and writes no catalog row: both go through a subagent, …` up to the end of that sentence with:

```python
# It researches nothing, and the only catalog row it writes is a staff member's own registry
# check (record_registry_check), which a person makes and the model only records. Research and
# promotion go through a subagent, so there is one path to a source and one path from research
# to the catalog, each under the instructions written for it.
```

Add to `TOOLS`, after `pending_resolutions`:

```python
    # registry_check_tools — a person's check, recorded with its evidence. Staff only, and
    # the supervisor's only: the researcher reads untrusted pages.
    record_registry_check,
```

- [ ] **Step 4: Name it in `instructions.md`**

(a) Insert after the `## Access rules are absolute` section (before `## Source priority`):

```markdown
## Registrations: a status, and who checked

A registration is a **status**, not a yes or a no, and the status says who could see it.

- `applied` is not `registered`. A Form 10AB acknowledgement is `applied`.
- `check_blocked` means somebody tried and the registry could not be read: a CAPTCHA, a sign-in or
  a network filter. It never means valid, and it is never `not_found`. A researcher that reports a
  `CHECK BLOCKED:` page or a refused registry has finished with it.
- `not_found` means a working source was read and did not list the registration.

When research comes back `check_blocked`, tell the user which registry and which registration,
and ask whether a staff member will check it by hand. When they have, and have uploaded what they
saw to the organisation's Doc Vault, record it with `record_registry_check(org, id_type, status,
evidence_document_id, note)`. Never record a check without the evidence document, and never one
you or a researcher inferred: a manual check is a person's act. The tool takes the checker from
the signed-in staff member, never from you.

Two kinds of source are read but never trusted on their own. An **aggregator** (Give.do,
GuideStar India) is read only on the paths its registry entry names, and every value from it is
`claimed`: a lead or a corroboration, never in place of the organisation's own document. The
team's **earlier research** (the org-grant-intelligence repository, pinned to one commit) is read
first, as a map of leads; its values are `prior_research` and `claimed`, its cited links are
re-read under their own rules, and where a primary source disagrees, the primary source wins and
the disagreement is reported under `conflicts`. Both rules are enforced when research is saved.
```

(b) In `## What you can write, and what you cannot`, add after the paragraph starting `**What promotion holds back, it names.**`:

```markdown
**One write is yours, not a subagent's:** a staff member's registry check, through
`record_registry_check`, with the document that shows it. It is the only catalog row you write.
```

(c) In `## Tools`, change the first paragraph to:

```markdown
Eight of your own, in three groups, plus three the harness adds. **You cannot open a web
page, and the only catalog row you write is a staff member's own registry check** — research
and promotion go through a subagent, which is why there is exactly one path to a source and one
path from research to the catalog.
```

Add after the adapter-path bullets:

```markdown
**A person's registry check** — staff only, with its evidence.

- `record_registry_check(org, id_type, status, evidence_document_id, note)` — records a check a
  staff member made by hand on a registry Sangam cannot read. Refused without an uploaded
  document of that organisation. It cites `[org:N]` and `[document:N]`.
```

- [ ] **Step 5: Label it**

In `frontend/features/ingest/lib/toolLabels.ts`, add to `TOOL_LABELS` after `pending_resolutions`:

```ts
  record_registry_check: {
    label: "Recording a manual registry check",
    detail: (a) => [a?.org, a?.id_type, a?.status].filter(Boolean).join(" · "),
  },
```

- [ ] **Step 6: Run the tests**

```bash
cd backend && pytest tests/test_harness.py tests/test_ingest.py tests/test_manual_checks.py -q -m "not integration" && ruff check .
cd frontend && npm ci && npm run lint && npm run build
```

Expected: all pass, including `test_instructions_name_every_registered_tool`, `test_every_tool_defined_is_also_registered`, `test_the_researcher_gets_its_…` (unchanged) and `test_neither_agent_can_write_a_file_or_run_a_command`. Lint and build are clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/ingest/tools/registry_check_tools.py backend/tests/test_manual_checks.py backend/app/ingest/agent.py backend/app/ingest/instructions.md frontend/features/ingest/lib/toolLabels.ts backend/tests/test_harness.py backend/tests/test_ingest.py
git commit -m "feat(ingest): record_registry_check on the supervisor; statuses in the prompt

record_registry_check is on the supervisor alone. It takes the checker from the
conversation, never an argument, and never raises. instructions.md states
applied vs registered, check_blocked vs not_found, and that aggregator and
prior-research values are claimed.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Hold a CSO-workbook funder block that names its own CSO (extends #99 plan (c))

**Files:**
- Modify: `backend/app/ingest/source_layouts.py`
- Modify: `backend/app/ingest/data/source_layouts/cso_programmes_and_funders.json`
- Modify: `backend/app/ingest/staff_sources.py`
- Modify: `scripts/upload_staff_source.py`
- Modify: `backend/tests/staff_source_fixtures.py`
- Test: `backend/tests/test_source_layouts.py`, `backend/tests/test_staff_sources.py`

**Interfaces:**

```python
SheetProfile.hold_self_named_blocks: bool = False                     # source_layouts.py
HELD_SELF_NAMED: str
def _names_itself(title: str, rows: list[SourceRow]) -> bool
def held_blocks(rows: Iterable[SourceRow]) -> list[tuple[str, str, int]]   # (sheet, block column, rows)
def render_held(doc_id: int, blocks: list[tuple[str, str, int]]) -> str   # staff_sources.py
cso_workbook(..., self_named: bool = False)                            # fixtures
```

Why a profile key and not a code-only change: plan (c)'s sidecar is keyed by the digest of the profile JSON. A parser-only change would leave every existing sidecar "current" and unflagged. The new key changes the digest, so old sidecars go stale and the workbook is re-parsed.

- [ ] **Step 1: Extend the fixture**

In `backend/tests/staff_source_fixtures.py`, change `_blocks_sheet(book, block_header)` to `_blocks_sheet(book, block_header, self_named=False)` and add at its end:

```python
    if self_named:
        # The block titled Moss Valley Society lists Moss Valley Society as one of its own funders:
        # most likely another CSO's table under the wrong title.
        _put(ws, 6, "K", ["Moss Valley Society", "Clinics", "2024-25", 90000])
```

Change `cso_workbook` to take `self_named: bool = False` and pass it to `_blocks_sheet(book, block_header, self_named)`.

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_source_layouts.py`:

```python
def test_a_block_naming_its_own_cso_as_a_funder_is_held():
    rows = [r for r in layouts.read_rows(cso_workbook(include=("profile", "blocks"), self_named=True), _cso())
            if r.sheet == "CSO Funder Details"]
    held = {r.cell for r in rows if "held" in r.context}
    assert held == {"K3", "K4", "K5", "K6"}, "the whole block, not only the self-naming row"
    assert all("held" not in r.context for r in rows if not r.cell.startswith("K"))


def test_no_block_is_held_when_none_names_itself():
    rows = layouts.read_rows(cso_workbook(include=("profile", "blocks")), _cso())
    assert not [r for r in rows if "held" in r.context]


def test_a_near_name_is_not_its_own_name():
    rows = [layouts.SourceRow(sheet="s", cell="K3", kind="funder", text={"funder": "Moss Valley Foundation"})]
    assert not layouts._names_itself("Moss Valley Society", rows)
    rows[0].text["funder"] = "The Moss Valley Society."
    assert layouts._names_itself("Moss Valley Society", rows)


def test_the_flag_changes_the_digest():
    import json as _j
    from importlib.resources import files as _files

    raw = _j.loads((_files("app.ingest") / "data" / "source_layouts" / "cso_programmes_and_funders.json")
                   .read_text(encoding="utf-8"))
    blocks = next(s for s in raw["sheets"] if s.get("layout") == "blocks_by_column")
    assert blocks["hold_self_named_blocks"] is True
    without = _j.loads(_j.dumps(raw))
    del next(s for s in without["sheets"] if s.get("layout") == "blocks_by_column")["hold_self_named_blocks"]
    assert layouts.parse_profile(raw).digest != layouts.parse_profile(without).digest


def test_the_flag_needs_a_titled_blocks_sheet():
    raw = {"name": "x", "source_key": "ffrh_funder_datasets", "filename_pattern": "x", "load": "full",
           "sheets": [{"sheet": "s", "layout": "table", "amount_unit": "inr", "hold_self_named_blocks": True,
                       "columns": [{"column": "A", "header": "Funder", "field": "funder"}]}]}
    with pytest.raises(LayoutError, match="hold_self_named_blocks"):
        layouts.parse_profile(raw)
```

Append to `backend/tests/test_staff_sources.py`:

```python
async def test_a_held_block_is_shown_without_marker_or_names(world, monkeypatch):
    data = cso_workbook(self_named=True)
    doc = _dataset(43, data, CSO)
    key = doc["storage_path"].partition("/")[2]
    world[key] = data
    world[staff_sources.sidecar_key(key, CSO)] = staff_sources.encode_rows(layouts.iter_rows(data, CSO))

    async def datasets(pool, *, source_keys=None):
        return [doc]

    monkeypatch.setattr(staff_sources.documents_repo, "list_source_datasets", datasets)
    out = await staff_sources.search(object(), "Moss Valley Society")
    assert "#CSO Funder Details:K" not in out, "no marker from a held block may be offered"
    assert "HELD for staff" in out and "column K" in out and "4 rows" in out
    held_part = out.split("HELD for staff", 1)[1]
    assert "Dune Foundation" not in held_part and "Moss Valley Society" not in held_part


def test_the_upload_reports_held_blocks_by_location_only():
    rows = layouts.read_rows(cso_workbook(self_named=True), CSO)
    assert staff_sources.held_blocks(rows) == [("CSO Funder Details", "K", 4)]
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_source_layouts.py tests/test_staff_sources.py -q -k "held or names_itself or near_name or flag"`
Expected: `KeyError: 'hold_self_named_blocks'` and `AttributeError: … '_names_itself'` / `'held_blocks'`.

- [ ] **Step 4: Implement in `source_layouts.py`**

(a) Add the field to `SheetProfile`, after `title_field`:

```python
    hold_self_named_blocks: bool = False
```

(b) Add the constant after `MODES`:

```python
HELD_SELF_NAMED = (
    "this block's rows name its own titled CSO as a funder, so it is most likely another CSO's table "
    "under the wrong title"
)
```

(c) In `parse_profile`, inside the loop before `sheets.append(...)`:

```python
        hold = s.get("hold_self_named_blocks", False)
        if not isinstance(hold, bool):
            raise LayoutError(f"{where}: hold_self_named_blocks must be true or false")
        if hold and (layout != "blocks_by_column" or not s.get("title_field")):
            raise LayoutError(f"{where}: hold_self_named_blocks needs a blocks_by_column sheet with a title_field")
```

and pass `hold_self_named_blocks=hold` to `SheetProfile(...)`.

(d) Add before `_read_blocks`:

```python
def _names_itself(title: str, rows: list[SourceRow]) -> bool:
    """Exact equality after normalising, never containment: "Moss Valley Foundation" is not
    "Moss Valley Society", and a substring match would hold a real funder's block."""
    own = normalise_name(title)
    return bool(own) and any(normalise_name(r.text.get("funder", "")) == own for r in rows)
```

(e) In `_read_blocks`, inside `for i, start in enumerate(starts):`:
- Before the inner `for r in range(…)` loop, add `block_rows: list[SourceRow] = []`.
- Replace the final `yield row` of the inner loop with `block_rows.append(row)`.
- After the inner loop, still inside the block loop, add:

```python
        # A self-named block is held whole, before anything is attributed from it (spec §4,
        # staff dataset note). The sheet is fixed at source; until then staff see where it is.
        if spec.hold_self_named_blocks and title and _names_itself(title, block_rows):
            for row in block_rows:
                row.context["held"] = HELD_SELF_NAMED
        yield from block_rows
```

(f) In `cso_programmes_and_funders.json`, add `"hold_self_named_blocks": true,` to the `CSO Funder Details` sheet object, after `"title_field": "cso",`.

- [ ] **Step 5: Implement in `staff_sources.py`**

Append:

```python
def held_blocks(rows: Iterable[layouts.SourceRow]) -> list[tuple[str, str, int]]:
    """(sheet, block column, row count) for every held block. Locations and counts, never content."""
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        if "held" in row.context:
            column = re.match(r"[A-Z]+", row.cell).group(0)
            counts[(row.sheet, column)] = counts.get((row.sheet, column), 0) + 1
    return [(sheet, column, n) for (sheet, column), n in counts.items()]


def render_held(doc_id: int, blocks: list[tuple[str, str, int]]) -> str:
    lines = [f"HELD for staff, not attributable — document {doc_id}:"]
    lines += [
        f"  sheet {sheet!r}, block at column {column} ({n} rows): {layouts.HELD_SELF_NAMED}. Nothing from it "
        f"may be saved or promoted. A person fixes the sheet at its source and re-uploads it."
        for sheet, column, n in blocks
    ]
    return "\n".join(lines)
```

Add `import re` to `staff_sources.py`'s imports if (c) has not. Add `Iterable` from `collections.abc` if absent.

In `search()`, right after `rows = await asyncio.to_thread(…)`, and **before** the `if years:` filter, split the held rows off:

```python
        held = held_blocks(rows)
        rows = [r for r in rows if "held" not in r.context]
        if held:
            problems.append(render_held(doc["id"], held))
```

The held rows are never rendered with a marker, their names never reach `matched`, and their content never reaches the output. Only the location and the count are reported, in the trailing problems block.

- [ ] **Step 6: Report held blocks at upload**

In `scripts/upload_staff_source.py`, after the line that prints `{result.status}: document …`, add:

```python
            for sheet, column, n in staff_sources.held_blocks(layouts.iter_rows(data, profile)):
                print(f"  HELD: sheet {sheet!r}, block at column {column}, {n} rows — it names its own CSO as a "
                      f"funder. Fix the sheet at its source and upload it again.")
```

`data`, `profile`, `layouts` and `staff_sources` are the names plan (c)'s script already binds. If the script binds them under other names, use those. The line prints a location and a count, never a row, which keeps (c)'s `test_… "print(row" not in source` guard true.

- [ ] **Step 7: Run the tests**

Run: `cd backend && pytest tests/test_source_layouts.py tests/test_staff_sources.py -q && ruff check .`
Expected: all pass, including every plan (c) test, which builds workbooks without `self_named`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/ingest/source_layouts.py backend/app/ingest/data/source_layouts/cso_programmes_and_funders.json backend/app/ingest/staff_sources.py scripts/upload_staff_source.py backend/tests/staff_source_fixtures.py backend/tests/test_source_layouts.py backend/tests/test_staff_sources.py
git commit -m "feat(ingest): hold a workbook funder block that names its own CSO

A block whose rows list its titled CSO as a funder is most likely another
CSO's table. It is held whole: never rendered with a marker or a name, so
nothing in it can be attributed, and the upload reports its location for
staff to fix the sheet. The profile flag changes the digest, so old sidecars
are rebuilt.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Rewrite `ngo-credential-research`

**Files:**
- Rewrite: `backend/app/ingest/skills/ngo-credential-research/SKILL.md`
- Test: `backend/tests/test_harness.py`

**Interfaces:** none.

The rewrite replaces plan (c)'s "A staff source: the CSO workbook" section. It keeps the three strings plan (c)'s `test_the_ngo_skill_names_the_staff_workbook` asserts: `read_source_rows`, `funder sheets` and `` `claimed` ``. It drops "Never cite an aggregator".

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_harness.py`:

```python
class TestTheCredentialSkill:
    """Spec §4 and §4a: generic, ordered, statuses not yes/no, and the documents to ask for."""

    @staticmethod
    def text() -> str:
        from app.ingest.agent import SKILLS_DIR

        return (SKILLS_DIR / "ngo-credential-research" / "SKILL.md").read_text(encoding="utf-8")

    def test_it_names_no_seeded_cso_or_funder(self):
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "seed" / "data"
        names = [json.loads(p.read_text())["entity_name"] for p in (root / "darpan").glob("*.json")]
        rubric = root / "rubrics" / "funders.json"
        if rubric.exists():
            names += [f["name"] for f in json.loads(rubric.read_text())]
        text = self.text().casefold()
        assert not [n for n in names if n and n.casefold() in text]

    def test_where_to_look_is_in_order(self):
        section = self.text().split("## Where to look, in this order", 1)[1].split("\n## ", 1)[0]
        marks = ["0. **The team's earlier research", "1. **The CSO's own documents", "2. **Registries",
                 "3. **Funders' own pages", "4. **Staff datasets", "5. **Aggregators"]
        positions = [section.index(m) for m in marks]
        assert positions == sorted(positions)
        assert "ngos/<cso>/" in section and "prior_research" in section and "manual_aggregator" in section

    def test_statuses_not_yes_or_no(self):
        text = self.text()
        for phrase in ("`applied`, never `registered`", "`check_blocked`", "never `not_found`",
                       "record_registry_check"):
            assert phrase in text, phrase

    def test_it_lists_the_documents_to_request(self):
        section = self.text().split("## Documents to request from the CSO", 1)[1].split("\n## ", 1)[0]
        for doc in ("trust deed", "PAN", "12AB", "80G", "CSR-1", "FCRA certificate", "three years of audited",
                    "three years of FCRA returns", "annual report"):
            assert doc in section, doc

    def test_the_old_aggregator_ban_is_gone(self):
        assert "Never cite an aggregator" not in self.text()

    def test_the_primary_source_wins_over_the_dossier(self):
        assert "the primary source wins" in self.text() and "`conflicts`" in self.text()
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_harness.py -q -k "CredentialSkill or ngo_skill"`
Expected: the order, status, documents, aggregator and primary-source tests fail. The names test passes. Plan (c)'s workbook test passes before and after.

- [ ] **Step 3: Replace the file**

Replace all of `backend/app/ingest/skills/ngo-credential-research/SKILL.md` with:

````markdown
---
name: ngo-credential-research
description: Use when someone names one or more NGOs, CSOs, trusts or societies — organisations that RECEIVE money — and wants their actual legal and operational standing rather than their sector and mission. Sets the order to read sources in (the team's earlier research as a map of leads, then the CSO's own documents, readable registries, funders' pages, staff datasets via read_source_rows, aggregators last) and what to pull — statutory registrations as statuses (applied, registered, check_blocked), three years of audited financials with foreign contribution received and unspent, existing funders with amounts, programmes and metrics, governance and staff, name variants, website. Lists exactly which documents to request from the CSO when no public source can confirm them. Raw field-value-source only; no verdicts, no scoring. Not for a company, corporate foundation or CSR arm — use funder-intake-research. Not for a single fact already in the catalog — funder_dossier with entity_kind org answers that.
---

# What we want pulled for an NGO

What follows goes into each researcher's task description: where to look, in which order, what to
pull, and how to label it. No organisation is special-cased here, and none should be.

## The rules that hold for every value

**Every value carries its exact source URL. Including "not stated".** A field with no findable URL
is not reported as a fact.

**Every value carries its source type and its evidence tier.** The source type is where it came
from: `org_document`, `registry`, `funder`, `staff_dataset`, `prior_research`, `aggregator`. The
evidence tier is `evidenced` or `claimed`, and nothing is ever silently upgraded from one to the
other. Evidenced means the document itself states the fact — a certificate, an audited statement,
a dated return, a registry record. "We are 12A and 80G registered" on a web page, with no number
and no certificate, is **claimed**: explicit, quotable, and still not evidence.

**A weaker source never replaces a stronger one.** Strongest first: a registry or a staff member's
manual check, then the CSO's own documents, then a funder's page, then a staff dataset, then the
team's earlier research, then an aggregator. Where two disagree, keep both, each with its source;
the catalog keeps the stronger and lists the other under `conflicts`.

**A blank government search form is not a source.** An empty search box renders identically for
every organisation and proves nothing about this one.

**Adverse findings hide in audited statements, not on homepages.** A suspended FCRA, a cancelled
12AB, a show-cause notice: check the notes and credential sections of the audited accounts. A
cancellation under appeal is still a cancellation; record the appeal as its own value.

**Pull raw.** Field, value, source URL, source type, evidence tier. No eligibility verdict, no
summary, no comparison table — those are downstream.

## Where to look, in this order

The order is strength of evidence, with one exception that comes first because it feeds the rest.

0. **The team's earlier research, as a map of leads.** The org-grant-intelligence repository holds
   a dossier per CSO under `ngos/<cso>/`: profile tables, annual-report summaries, programmes and
   the links each fact came from. List the folder through the pinned directory listing, read its
   `.md` files at the pinned commit, and save their facts with `source_type = 'prior_research'`
   and `claimed`, citing the dossier file's pinned URL. Then treat **every link the dossier cites
   as a lead**: re-read the primary ones under their own access rules — the CSO's own site, a
   funder's page, a registry — and save what they show with that source's own type. Aggregator
   links a dossier cites are re-read only under `manual_aggregator`, as in step 5. A dossier can
   be out of date: where it and a primary source disagree, **the primary source wins** and the
   disagreement is reported under `conflicts`.
1. **The CSO's own documents.** Uploaded ones in the Doc Vault first, then those on its site:
   - the trust deed, society registration or Section 8 certificate;
   - the PAN card;
   - the 12AB and 80G orders (Forms 10AC / 10AD), or a Form 10AB acknowledgement;
   - the CSR-1 approval;
   - the FCRA certificate and its latest renewal;
   - FCRA returns (FC-4);
   - audited accounts;
   - annual reports;
   - policies.
2. **Registries, where a machine may read them.** Where one sits behind a CAPTCHA, a sign-in or a
   network filter, do not try to get past it. The registration is `check_blocked`, never
   `not_found` and never assumed valid. Say which registry, so a staff member can check it by hand;
   the supervisor records that check with `record_registry_check`, with the evidence uploaded.
3. **Funders' own pages naming the CSO as a grantee**, and company CSR filings naming it as the
   organisation that carried out the work. Match on name **and** district or state: short names
   collide.
4. **Staff datasets**, through `read_source_rows` with the organisation's name: the internal CSO
   workbook (a profile sheet and two funder sheets) and the CSR filings. Each row carries a
   `[source:<document>#<sheet>:<cell>]` marker; quote the line with its marker, and use the
   dataset's `source_url` the tool prints. The profile sheet is the CSO's self-reported record, so
   every value from it is `claimed`. The funder sheets give its funders by year with amounts, also
   `claimed` until a funder's or the CSO's published document confirms them. A block the tool
   reports as **HELD for staff** names its own CSO as a funder and is most likely another CSO's
   table: nothing from it is saved.
5. **Aggregators, last, under `manual_aggregator`.** Give.do's public `/discover/` pages and
   GuideStar India's public search, one CSO at a time. Corroboration and gap-filling only. Every
   value is `claimed` with `source_type = 'aggregator'`, and none replaces the CSO's own document.
   An aggregator listing a registration the CSO's own files show only as an application is a
   conflict to report, not a registration.

## What to pull

**Statutory status as a status, not a yes or a no.**
- A Form 10AB acknowledgement is `applied`, never `registered`; keep its acknowledgement number as
  the application reference.
- A registry that cannot be read is `check_blocked`, never `not_found`. `not_found` means a working
  source was read and does not list it.
- When the FCRA portal cannot be read, take the registration number from the CSO's own FCRA
  returns and leave its validity `check_blocked`.
- Section 8 companies: some funders, government PSUs especially, exempt them from 12A/80G. Record
  that the organisation is one, because whether the gate blocks depends on the funder.
- CSR-1: the registration number, and whether the filing names the certifying professional.
- DARPAN: the ID, and the blacklist status where a lookup is possible. Recording the ID is not
  checking it.

**Financials, by year, from the audited statements.** Three years where they exist:
- income, expenditure, and surplus or deficit;
- programme and non-programme spend where stated;
- foreign contribution received, and foreign contribution left unspent at year end, from the FCRA
  returns.

Quote any internal inconsistency in the audit verbatim in the notes. Record the actual years
covered and which are missing, not "audits exist".

**Existing funders, with amounts, from four places:** grant lines in the audited accounts, donors
in the FCRA returns, funders' grantee pages, and company CSR filings and the staff funder sheets.
Each is a `partner` finding on the funder's side, with its amount as printed and its unit, and its
year. Promotion stores it in rupees on that funder's `kind = 'partner'` line.

**Programmes and metrics** from the annual reports, each with its year, `claimed`. A target only
when the report states one.

**Governance and capacity:**
- the board, as `office_bearer` contacts — names and roles only, never personal email or phone;
- the staff count with a note saying what it counts ("20+ full-time professionals, team page");
  permanent staff, not volunteers or contractors, where the source says which;
- the policies, each as a `policy` document: child safeguarding, HR, finance and procurement,
  grievance, an organogram. Record which are published and which are absent; never infer one.

Where the CSO's own pages give different counts — trustees on one page, another number on the
next — record every count with its source. Do not pick one.

**Name variants**, as aliases: every spelling seen in any source, including the filings'.

**The website, a one-paragraph description, and social links.**

## Documents to request from the CSO

When no public source confirms a credential, ask the CSO for it through the Doc Vault, naming
exactly these:

- the registration certificate or trust deed;
- the PAN card;
- the 12AB and 80G orders (Forms 10AC and 10AD), or the Form 10AB acknowledgement;
- the CSR-1 approval;
- the FCRA certificate and its latest renewal;
- three years of audited accounts;
- three years of FCRA returns;
- the latest annual report.

## Two things to confirm before anything else

**It is the right organisation.** Namesakes are common. Confirm against the organisation's own
materials before any budget is spent.

**Where it actually works.** Registered in one state and working mainly in another is common
enough to check, from the organisation's own materials rather than a prior list's assumption.

## What this skill does not do

It does not produce an eligibility verdict, score the organisation, rank a list or lay out a
comparison. It does not write to the catalog, and it does not record a manual check. It produces
cited values, with their source types and tiers, and stops.
````

- [ ] **Step 4: Run the tests**

Run: `cd backend && pytest tests/test_harness.py -q`
Expected: all pass, including `test_every_skill_is_one_directory_deep_with_matching_frontmatter` and plan (c)'s `test_the_ngo_skill_names_the_staff_workbook`. Confirm the description length is ≤ 1024 with:

```bash
cd backend && python -c "import yaml;t=open('app/ingest/skills/ngo-credential-research/SKILL.md').read().split('---')[1];print(len(yaml.safe_load(t)['description']))"
```

Expected: a number below 1024.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingest/skills/ngo-credential-research/SKILL.md backend/tests/test_harness.py
git commit -m "docs(skills): rewrite ngo-credential-research as an ordered, status-based brief

Prior research first as a map of leads, then the CSO's own documents,
readable registries, funders' pages, staff datasets and aggregators last.
Statuses not yes/no; financials with foreign contribution unspent; existing
funders with amounts; the documents to request from the CSO. Generic.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: The researcher's prompt, the two dependent skills, and the docs

**Files:**
- Modify: `backend/app/ingest/prompts/entity_researcher.md`
- Modify: `backend/app/ingest/skills/entity-record/SKILL.md`, `backend/app/ingest/skills/ngo-brief-for-funders/SKILL.md`
- Modify: `docs/SKILLS.md`, `docs/INGEST.md`
- Test: `backend/tests/test_ingest.py`, `backend/tests/test_harness.py`

**Interfaces:** none.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_ingest.py`:

```python
class TestTheResearcherCarriesTheCsoRules:
    """The researcher loads no skill, so every hard rule is in its own prompt."""

    @staticmethod
    def prompt() -> str:
        from app.ingest.agent import prompt

        return prompt("entity_researcher")

    def test_the_hard_rules_are_in_the_prompt(self):
        text = self.prompt()
        for phrase in ("`applied`, never `registered`", "`check_blocked`, never `not_found`", "CHECK BLOCKED:",
                       "source_type 'aggregator'", "source_type 'prior_research'", "evidence_tier 'claimed'",
                       "the primary source wins", "Never try to get past"):
            assert phrase in text, phrase

    def test_the_prompt_pins_the_commit_the_registry_pins(self):
        repo = SOURCES["org_grant_intelligence"]
        index = SOURCES["org_grant_intelligence_index"]
        text = self.prompt()
        assert f"https://{repo.host}{repo.allowed_paths[0]}" in text
        assert f"https://{index.host}{index.allowed_paths[0]}" in text and dict(index.allowed_query)["ref"] in text

    def test_the_org_section_no_longer_says_funders_have_nowhere_to_go(self):
        org = self.prompt().split("## What to extract — an `org`", 1)[1].split("\n## ", 1)[0]
        assert "the only place the fact survives" not in org
        assert "`partner` finding" in org and "website" in org and "staff_count" in org
```

Append to `backend/tests/test_harness.py`:

```python
def test_the_record_and_brief_skills_know_what_is_now_stored():
    from app.ingest.agent import SKILLS_DIR

    record = (SKILLS_DIR / "entity-record" / "SKILL.md").read_text(encoding="utf-8")
    brief = (SKILLS_DIR / "ngo-brief-for-funders" / "SKILL.md").read_text(encoding="utf-8")
    for text in (record, brief):
        assert "has no finding behind it" not in text
        assert "check_blocked" in text
    assert "has no column" not in brief
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_ingest.py tests/test_harness.py -q -k "CsoRules or now_stored"`
Expected: failures on the missing phrases and on "has no finding behind it".

- [ ] **Step 3: The researcher's prompt**

In `backend/app/ingest/prompts/entity_researcher.md`:

(a) In `## Access rules are absolute`, append after the paragraph ending `A \`REFUSED:\` reply is a final answer.`:

```markdown
A `CHECK BLOCKED:` reply means the page was a wall — a CAPTCHA, a sign-in, a 401/403/429 — and
nothing on it was read. Never try to get past one: no other route, no cache, no mirror. A
registration that page would have confirmed is `check_blocked`, never `not_found`; say which
registry in your summary so a staff member can check it by hand. `not_found` is only for a
working source you read that does not list it. The same goes for a `REFUSED:` registry.

Two sources are readable on named paths only, and their values are never more than claimed:

- **Aggregators** — Give.do's public `/discover/<code>/<name>/` pages, and GuideStar India's
  public search API,
  `https://guidestarindia.frappe.cloud/api/method/guidestar.api.npo_profile.npo_profile_search?keyword=<name>&page_no=1`.
  Save every value from them with source_type 'aggregator' and evidence_tier 'claimed'. They
  corroborate or fill a gap; they never replace the organisation's own document.
- **The team's earlier research** — the org-grant-intelligence repository at one pinned commit.
  List a folder with
  `https://api.github.com/repos/project-tech4dev/org-grant-intelligence/contents/<path>?ref=414cd6968765bcfff758632797dcbb8d00363ab2`
  and read a file at
  `https://raw.githubusercontent.com/project-tech4dev/org-grant-intelligence/414cd6968765bcfff758632797dcbb8d00363ab2/<path>`.
  Save its values with source_type 'prior_research' and evidence_tier 'claimed', citing that
  pinned URL. Then re-read the links it cites, each under its own access rules, and save what a
  primary source shows with that source's own type: where they disagree, the primary source wins
  and you keep both findings, so the difference is reported.

`save_research` refuses a finding from either source that is not labelled this way, and an
`org_identifier` saved as `not_found` from a registry Sangam cannot read.
```

(b) Replace everything from the line `## What to extract — an \`org\`` up to, but not including, the line `## Rules that decide whether a fact is usable` with:

```markdown
## What to extract — an `org`

**Start with the team's earlier research.** List `ngos/` at the pinned commit (above), find the
organisation's folder, and read its `.md` files. They are a map of leads, not facts: save what
they state as `prior_research`, `claimed`, and then go to the links they cite.

Then work strongest-source-first: the organisation's own documents (its Doc Vault uploads and its
site), readable registries, funders' pages naming it, the staff datasets through
`read_source_rows`, and aggregators last. Every org finding carries a `source_type` —
`org_document`, `registry`, `funder`, `staff_dataset`, `prior_research` or `aggregator` — and an
`evidence_tier`: `evidenced` only when the document itself states the fact (a certificate, an
audited statement, a dated return), `claimed` otherwise.

An NGO keeps four concepts unchanged — **programs**, **metrics**, **contacts** and **documents**,
the same tables with an `org_id`. Its own:

1. **org_identity** — name, `org_kind` (`cso`, `intermediary`, `government`), legal form as
   printed, registration date, **website**, a one-paragraph **description**, **aliases** (every
   spelling any source uses, the filings' included), and **staff_count** with a note saying what it
   counts ("20+ full-time professionals, team page"). Different counts on different pages are all
   recorded, each with its source.
2. **org_identifier** — 12A, 80G, FCRA, PAN, CSR-1, Darpan, CIN, registration number, each with a
   **status**: a Form 10AB acknowledgement is `applied`, never `registered`, and its number is the
   application reference; a registry you could not read is `check_blocked`, never `not_found`;
   when the FCRA portal is unreachable, take the number from the organisation's FCRA returns and
   leave validity `check_blocked`. **Never guess an identifier.**
3. **org_financials** — per FY from the audited statements: total income, programme and
   non-programme spend, foreign contribution received and **foreign contribution unspent** at year
   end (from the FCRA return), whether audited. Quote any inconsistency in the audit verbatim in
   `notes`.
4. **org_locations** — state and district, role `registered`, `operates` or `funds`. A district
   always travels with its state.

**Its funders are findings now.** Each funder that gave it money — a grant line in the audited
accounts, a donor in an FCRA return, a funder's grantee page, a CSR filing, a staff funder sheet —
is a `partner` finding on the funder's side, naming this organisation as the partner, with the
amount as printed and its unit, and the fiscal year. Never record a grant the NGO received as if
the NGO gave it.

**Contacts** are the board, as `office_bearer` — names and roles only, never a personal email or
phone. **Documents** include each published policy, as `policy`.
```

- [ ] **Step 4: The two dependent skills**

In `backend/app/ingest/skills/entity-record/SKILL.md`:

(a) Replace item 2 of the receiving-money order (from `2. **Statutory standing**` up to the end of that item) with:

```markdown
2. **Statutory standing** — 12A, 80G, CSR-1 and its registration number, PAN, DARPAN with
   blacklist status, FCRA kept separate. Each with its number and its **status** — registered,
   applied, check_blocked, not_found, expired, suspended or cancelled — and who established it:
   a document, a registry, or a staff member's manual check with its evidence. `applied` is not
   registered, and `check_blocked` is never shown as valid. A cancelled or suspended registration
   appears here, not in a footnote, with its appeal status beside it.
```

(b) Replace item 6 (from `6. **Who funds it already**` up to the end of that item) with:

```markdown
6. **Who funds it already** — named funders with year and amount, from the funder-side
   `partner` lines that name this organisation (`funder_activity`, `kind = 'partner'`), each with
   its source. Write "not recorded" rather than omitting the heading.
```

(c) Replace item 7 with:

```markdown
7. **Governance and capacity** — board, staff count with its note, institutional policies.
   Conflicting counts are shown together, each with its source.
```

(d) In `## Every line`, after the bullet `- **evidenced** or **claimed**, shown, never silently upgraded`, add:

```markdown
- the **source type** when it is not the organisation's own document — `aggregator`,
  `prior_research`, `staff_dataset` — because a claimed value from an aggregator and one from
  the organisation's own page are not the same weight
```

In `backend/app/ingest/skills/ngo-brief-for-funders/SKILL.md`:

(a) In `## The table`, replace `**statutory standing** — 12A, 80G, CSR-1, each present or not, with the blocking one named` with `**statutory standing** — 12A, 80G, CSR-1, each by status (registered · applied · check_blocked · not found), with the blocking one named`.

(b) Replace the paragraph starting `**Existing funders has no finding behind it.**` with:

```markdown
**Existing funders come from the funder-side partner lines** that name the organisation, each
with year and amount and its source. Write "not recorded" rather than leaving the cell empty.

**`applied` does not clear a gate, and `check_blocked` is not a pass.** A 12A that is only an
application, or an FCRA nobody could read, is named as the blocking gate with its status.
```

(c) Replace the whole `## What is stored and what is not` section with:

```markdown
## What is stored and what is not

An organisation's research promotes, so the comparison may well be describing rows the catalog
holds — the website, the staff count and each registration's status included. What it does not
hold, a cell that depends on it says so: a value an aggregator or earlier research claimed and no
primary source has confirmed, and any figure the catalog already states differently — that
difference is listed under conflicts, not stored over the stronger value.
```

- [ ] **Step 5: The docs**

In `docs/SKILLS.md`, add after the paragraph that ends `…test holds that for tools: \`test_a_tool_is_never_reachable_only_through_a_skill\`.`:

```markdown
The NGO side shows where that line falls. `ngo-credential-research` sets the source order and
the documents to ask a CSO for — procedure, so a skill. Five of its rules are constraints, so
they also sit in the researcher's prompt and the supervisor's instructions, and are enforced in
code (`app/ingest/source_guards.py`, `app/ingest/access.py`): `applied` is not `registered`;
`check_blocked` is never `not_found`; nothing gets past a CAPTCHA or a sign-in; an aggregator's
value is `claimed`; and so is a value from the team's earlier research until a primary source is
re-read. The researcher loads no skill, so a rule that lived only in the skill would not reach the
agent that needs it.
```

In `docs/INGEST.md`, in `## Sources: access rules are config, not comments`:

(a) Replace the sentence `Only \`open_api\` and \`crawl_allowed\` are dispatchable. Everything else is reported as **refused**, …` and its paragraph with:

```markdown
Only `open_api` and `crawl_allowed` are dispatchable. Two more rules are **path-scoped**: read
by the researcher's fetch tools one URL at a time, on the paths an entry names and nothing else,
never by an adapter.

- `manual_aggregator` — Give.do's public `/discover/` pages and GuideStar India's public search
  API. Every value is `claimed`.
- `internal_research` — the team's earlier research repository, readable only at one pinned
  commit (`raw.githubusercontent.com`) and through its pinned directory listing
  (`api.github.com`). Every value is `prior_research` and `claimed` until a primary source is
  re-read.

Everything else is reported as **refused**, with its basis, so "give.do: terms bar data mining" is
a row in the report rather than a crawl that should never have happened — and still is, for every
give.do path the aggregator entry does not name.
```

(b) Replace the paragraph starting `A source is a **product, not a host**` with:

```markdown
A source is a **product, not a host**: `mcacdm.nic.in` carries several. `rule_for_url()` first
looks for a path-scoped entry that claims the URL's path; otherwise it resolves the host to the
**strictest** rule among its other products, so declaration order can never decide whether a
crawler runs, and a path-scoped entry can never unlock a path it does not name.
```

(c) Regenerate the category table and the three-state counts from the registry, and paste the printed numbers into the two tables:

```bash
cd backend && python - <<'EOF'
from app.ingest.sources import SOURCES, Category
from app.ingest.runner import ADAPTERS
for c in Category:
    s = [x for x in SOURCES.values() if c in x.categories]
    print(c.value, len(s), sum(x.dispatchable for x in s))
print("total", len(SOURCES))
print("pulls", sum(k in ADAPTERS for k in SOURCES), "permitted", sum(x.dispatchable and x.key not in ADAPTERS
      for x in SOURCES.values()), "held", sum(not x.dispatchable and not x.path_scoped for x in SOURCES.values()),
      "path-scoped", sum(x.path_scoped for x in SOURCES.values()))
EOF
```

Add a fourth row to the three-state table, `| **path-scoped** | <n> | read by the researcher on named paths only; values claimed |`, and change "Three states" to "Four states". Update the "**74 sources**" sentence to the printed total.

(d) After the paragraph that starts ``\`read_page\` and \`fetch_document\` check twice before fetching``, add:

```markdown
They check again on **every redirect hop**, before requesting it: a request hook runs
`check_url` per hop, so a permitted page that redirects to a refused one is refused unrequested.
A 401/403/429, a sign-in page or a short CAPTCHA page comes back as `CHECK BLOCKED:` — not "not
found" — and a registration it would have confirmed is `check_blocked`. Registry checks a machine
cannot make are recorded by staff through the supervisor's `record_registry_check`, with the
uploaded evidence.
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest tests/test_ingest.py tests/test_harness.py -q && ruff check .`
Expected: all pass, including `test_a_subagent_prompt_names_every_tool_its_spec_declares`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/ingest/prompts/entity_researcher.md backend/app/ingest/skills/entity-record/SKILL.md backend/app/ingest/skills/ngo-brief-for-funders/SKILL.md docs/SKILLS.md docs/INGEST.md backend/tests/test_ingest.py backend/tests/test_harness.py
git commit -m "docs(ingest): the researcher's CSO rules, and skills that know what is stored

The researcher's prompt carries the hard rules (statuses, walls, claimed
sources, pinned prior research) and an org section with website, aliases,
staff count, foreign contribution unspent and funders as partner findings.
entity-record and ngo-brief-for-funders stop saying funders and websites have
nowhere to go. SKILLS.md and INGEST.md describe path-scoped rules.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Full verification and the acceptance run (spec §5)

**Files:** none changed, except a fix any check turns up. Each fix is its own commit, with a test.

- [ ] **Step 1: The whole suite**

```bash
cd backend && ruff check . && pytest -q -m "not integration"
cd backend && pytest -q -m integration           # needs this worktree's stack migrated, (d) and (e) in
cd frontend && npm ci && npm run lint && npm run build
```

Expected:
- ruff is clean;
- every unit test passes;
- integration passes, including `TestTheWriteAgainstTheSchema` and (d)'s migration integrity test;
- lint and build are clean.

- [ ] **Step 2: A scratch database, never the running site's**

The running site keeps its own stack and database. The acceptance run uses a scratch database on the same Postgres server, populated from a dump, with a backend and frontend run from **this worktree** on other ports:

Every command addresses the server by its published host port, never through `docker compose exec`. Run from the worktree, `docker compose` resolves a different compose project with no running container; run from the site's checkout, it would act on the site's own server. The client runs in a throwaway `postgres:16` container on the host network:

```bash
PG="docker run --rm -i --network host -e PGPASSWORD=sangam postgres:16"
$PG psql "host=localhost port=5433 user=sangam dbname=postgres" -c "CREATE DATABASE sangam_cso_accept"
$PG sh -c 'pg_dump --no-owner "host=localhost port=5433 user=sangam dbname=sangam" \
  | psql -q "host=localhost port=5433 user=sangam dbname=sangam_cso_accept"'
cd backend && MIGRATIONS_DIR=../db/migrations \
  DATABASE_URL="host=localhost port=5433 user=sangam password=sangam dbname=sangam_cso_accept" \
  python -m app.db.migrate
cd backend && DATABASE_URL="host=localhost port=5433 user=sangam password=sangam dbname=sangam_cso_accept" \
  ALLOWED_ORIGINS=http://localhost:3020 uvicorn app.main:app --port 8020
cd frontend && npm ci && AGENT_URL=http://localhost:8020/agent NEXT_PUBLIC_API_URL=http://localhost:8020 \
  npx next dev -p 3020
```

On macOS, Docker Desktop's `--network host` needs host networking enabled. Where it is not, use `host=host.docker.internal` in the two connection strings inside the container.

Expected: `CREATE DATABASE` and the dump succeed. `migrate` applies (c)'s, (d)'s and (e)'s migrations, plus any this PR depends on, and prints them. The backend logs `Sangam agent ready`.

The person running this exports the model, Storage and auth variables in their own shell first. Never print them, and never read `.env` through a tool. They then sign in at `http://localhost:3020` as a staff user.

- [ ] **Step 3: Two checks before the run**

1. **The checker reaches the tool.** In the Import chat, as staff, ask Import to record a manual check on a throwaway organisation created in the scratch database for this step, with a document uploaded to its vault. A reply of `REFUSED: no signed-in staff member is attached to this conversation` means `chat_user_id` does not reach tool execution. That is a defect in this plan's Task 7, not a user error: stop, fix it with a test, and commit before continuing.
2. **The baseline.** Run check 8's checklist query below for the test CSO **before** re-profiling, and record the number. The spec's "about 46%" came from a different list, so the 75% target is judged against this baseline, on the same measure.

- [ ] **Step 4: Re-profile the test CSO through Import**

The test CSO is the one spec §5 names. It is chosen by the person running the run and is not written into this plan, the PR or a commit.

1. In the Import chat, ask for it to be researched and pushed.
2. When the researcher reports a `check_blocked` registry (FCRA validity is expected to be one), a staff member checks it by hand and uploads the screenshot to the CSO's Doc Vault. They then ask Import to record it, giving the document id.

Then set `\set org <id>` in psql (`DATABASE_URL` as above) and check each item. Record pass/fail per check in the PR, as counts and statuses only: no names, numbers or figures from the CSO.

1. **Statuses.**

   ```sql
   SELECT id_type, status, check_method FROM org_identifiers WHERE org_id = :org AND is_current ORDER BY 1;
   ```

   Expected:
   - PAN `registered`;
   - 12A and 80G `applied` (the CSO's own Form 10AB acknowledgements);
   - FCRA `check_blocked`, or the status the staff member's manual check recorded, with `check_method = 'manual_check'`, `checked_by` set and `evidence_document_id` pointing at a document whose `org_id = :org`.
2. **Financials.**

   ```sql
   SELECT fiscal_year, total_income IS NOT NULL, foreign_unspent IS NOT NULL, source_type, evidence
   FROM org_financials WHERE org_id = :org ORDER BY 1;
   ```

   Expected: three years, each with `foreign_unspent` where the FCRA return states it, and `source_type = 'org_document'`.
3. **Partner lines.**

   ```sql
   SELECT count(*), count(DISTINCT source_name) FROM funder_activity
   WHERE partner_org_id = :org AND kind = 'partner' AND amount IS NOT NULL;
   ```

   Expected: lines with amounts from at least three kinds of source: the audited accounts or FCRA returns, a funder's page or CSR filing, and the staff funder sheet.
4. **Aliases.** Every spelling the filings use resolves: `resolve_org` on each spelling the researcher reported returns `:org`.
5. **Aggregator never overwrites.**

   ```sql
   SELECT count(*) FROM org_financials WHERE org_id = :org AND source_type = 'aggregator';
   ```

   Expected: 0 for any year that also has an audited figure. The catalog-writer's report lists the aggregator's figure under `conflicts`, beside the audited one.
6. **Prior research lands claimed.**

   ```sql
   SELECT count(*) FILTER (WHERE f->>'source_type' = 'prior_research') AS dossier,
          count(*) FILTER (WHERE f->>'source_type' = 'prior_research' AND f->>'evidence_tier' <> 'claimed') AS bad
   FROM entity_research r, jsonb_array_elements(r.findings) f
   WHERE r.slug = (SELECT slug FROM orgs WHERE id = :org);
   ```

   Expected: `dossier > 0` and `bad = 0`. Every `source_url` of those findings starts with the pinned raw prefix.

   Then check that the dossier's facts also **land** in the catalog as claimed:

   ```sql
   SELECT sum(n) AS landed, sum(bad) AS bad FROM (
     SELECT count(*) n, count(*) FILTER (WHERE evidence <> 'claimed') bad FROM orgs WHERE id = :org AND source_type = 'prior_research'
     UNION ALL SELECT count(*), count(*) FILTER (WHERE evidence <> 'claimed') FROM org_identifiers WHERE org_id = :org AND source_type = 'prior_research'
     UNION ALL SELECT count(*), count(*) FILTER (WHERE evidence <> 'claimed') FROM org_financials WHERE org_id = :org AND source_type = 'prior_research'
     UNION ALL SELECT count(*), count(*) FILTER (WHERE evidence <> 'claimed') FROM org_locations WHERE org_id = :org AND source_type = 'prior_research'
     UNION ALL SELECT count(*), count(*) FILTER (WHERE evidence <> 'claimed') FROM contacts WHERE org_id = :org AND source_type = 'prior_research'
     UNION ALL SELECT count(*), count(*) FILTER (WHERE evidence <> 'claimed') FROM programs WHERE org_id = :org AND source_type = 'prior_research'
     UNION ALL SELECT count(*), count(*) FILTER (WHERE evidence <> 'claimed') FROM metrics WHERE org_id = :org AND source_type = 'prior_research'
   ) s;
   ```

   Expected: `landed >= 1` and `bad = 0`. A dossier fact that no primary source re-read is stored as prior research; one that a primary source re-read is stored under that source instead (check 7).
7. **A primary fact outranks a dossier value.** The catalog-writer's report lists at least one `conflicts` entry whose losing value is `prior_research`, while the stored row carries the primary source's `source_type`. For example, a dossier that lists a registration as granted, where the CSO's own files show an application: the stored status is `applied`, with `source_type = 'org_document'`.
8. **Coverage of at least 75%, against about 46% before.** This is the 37-field checklist:

   ```sql
   SELECT count(*) FILTER (WHERE stored) AS stored, count(*) AS fields,
          round(100.0 * count(*) FILTER (WHERE stored) / count(*)) AS pct
   FROM (VALUES
     ('name',               (SELECT name IS NOT NULL FROM orgs WHERE id = :org)),
     ('org_kind',           (SELECT org_kind IS NOT NULL FROM orgs WHERE id = :org)),
     ('legal_form',         (SELECT legal_form IS NOT NULL FROM orgs WHERE id = :org)),
     ('registration_date',  (SELECT registration_date IS NOT NULL FROM orgs WHERE id = :org)),
     ('registered_location',(SELECT registered_location_id IS NOT NULL FROM orgs WHERE id = :org)),
     ('website',            (SELECT website IS NOT NULL FROM orgs WHERE id = :org)),
     ('description',        (SELECT description IS NOT NULL FROM orgs WHERE id = :org)),
     ('aliases',            (SELECT cardinality(aliases) > 0 FROM orgs WHERE id = :org)),
     ('staff_count',        (SELECT staff_count IS NOT NULL FROM orgs WHERE id = :org)),
     ('pan',    EXISTS (SELECT 1 FROM org_identifiers WHERE org_id = :org AND id_type = 'pan')),
     ('12a',    EXISTS (SELECT 1 FROM org_identifiers WHERE org_id = :org AND id_type = '12a')),
     ('80g',    EXISTS (SELECT 1 FROM org_identifiers WHERE org_id = :org AND id_type = '80g')),
     ('fcra',   EXISTS (SELECT 1 FROM org_identifiers WHERE org_id = :org AND id_type = 'fcra')),
     ('csr1',   EXISTS (SELECT 1 FROM org_identifiers WHERE org_id = :org AND id_type = 'csr1')),
     ('darpan', EXISTS (SELECT 1 FROM org_identifiers WHERE org_id = :org AND id_type = 'darpan')),
     ('reg_no', EXISTS (SELECT 1 FROM org_identifiers WHERE org_id = :org AND id_type = 'reg_no')),
     ('fy1 income',   (SELECT total_income IS NOT NULL FROM org_financials WHERE org_id = :org ORDER BY fiscal_year DESC LIMIT 1)),
     ('fy1 programme',(SELECT program_spend IS NOT NULL FROM org_financials WHERE org_id = :org ORDER BY fiscal_year DESC LIMIT 1)),
     ('fy1 fc',       (SELECT foreign_contribution IS NOT NULL FROM org_financials WHERE org_id = :org ORDER BY fiscal_year DESC LIMIT 1)),
     ('fy1 fc unspent',(SELECT foreign_unspent IS NOT NULL FROM org_financials WHERE org_id = :org ORDER BY fiscal_year DESC LIMIT 1)),
     ('fy2 income',   (SELECT total_income IS NOT NULL FROM org_financials WHERE org_id = :org ORDER BY fiscal_year DESC OFFSET 1 LIMIT 1)),
     ('fy2 programme',(SELECT program_spend IS NOT NULL FROM org_financials WHERE org_id = :org ORDER BY fiscal_year DESC OFFSET 1 LIMIT 1)),
     ('fy2 fc',       (SELECT foreign_contribution IS NOT NULL FROM org_financials WHERE org_id = :org ORDER BY fiscal_year DESC OFFSET 1 LIMIT 1)),
     ('fy2 fc unspent',(SELECT foreign_unspent IS NOT NULL FROM org_financials WHERE org_id = :org ORDER BY fiscal_year DESC OFFSET 1 LIMIT 1)),
     ('fy3 income',   (SELECT total_income IS NOT NULL FROM org_financials WHERE org_id = :org ORDER BY fiscal_year DESC OFFSET 2 LIMIT 1)),
     ('fy3 programme',(SELECT program_spend IS NOT NULL FROM org_financials WHERE org_id = :org ORDER BY fiscal_year DESC OFFSET 2 LIMIT 1)),
     ('fy3 fc',       (SELECT foreign_contribution IS NOT NULL FROM org_financials WHERE org_id = :org ORDER BY fiscal_year DESC OFFSET 2 LIMIT 1)),
     ('fy3 fc unspent',(SELECT foreign_unspent IS NOT NULL FROM org_financials WHERE org_id = :org ORDER BY fiscal_year DESC OFFSET 2 LIMIT 1)),
     ('operates',  EXISTS (SELECT 1 FROM org_locations WHERE org_id = :org AND role = 'operates')),
     ('board',     EXISTS (SELECT 1 FROM contacts WHERE org_id = :org AND kind = 'office_bearer')),
     ('programmes',EXISTS (SELECT 1 FROM programs WHERE org_id = :org)),
     ('metrics',   EXISTS (SELECT 1 FROM metrics WHERE org_id = :org)),
     ('deed or certificate', EXISTS (SELECT 1 FROM documents WHERE org_id = :org AND doc_type IN ('trust_deed', 'registration_certificate'))),
     ('audit report',  EXISTS (SELECT 1 FROM documents WHERE org_id = :org AND doc_type = 'audit_report')),
     ('annual report', EXISTS (SELECT 1 FROM documents WHERE org_id = :org AND doc_type = 'annual_report')),
     ('fcra return',   EXISTS (SELECT 1 FROM documents WHERE org_id = :org AND doc_type = 'fcra_return')),
     ('policy',        EXISTS (SELECT 1 FROM documents WHERE org_id = :org AND doc_type = 'policy'))
   ) AS checklist(field, stored);
   ```

   Expected: `fields = 37` and `stored >= 28` (that is, `pct >= 76`), against the Step 3 baseline. A NULL from a missing year counts as not stored.
9. **The fetch gate held.** Search the backend log for the run: every `give.do` URL fetched is under `/discover/`; every `raw.githubusercontent.com` URL carries the pinned commit; no `REFUSED: … redirected to` reply was followed by a fetch of its target.

- [ ] **Step 5: Tear down the scratch database**

Stop the 8020 backend and the 3020 frontend first, then:

```bash
docker run --rm --network host -e PGPASSWORD=sangam postgres:16 \
  psql "host=localhost port=5433 user=sangam dbname=postgres" -c "DROP DATABASE sangam_cso_accept"
```

- [ ] **Step 6: The PR description must say**

- **Order:** after #99 (a)–(c) and this spec's (d) and (e).
- **The give.do posture change.** C8 lets the researcher read `/discover/` pages one CSO at a time. Every other give.do path keeps the `give` entry's `no_scraping` refusal. A reviewer signs this off as a security decision.
- **GuideStar India.** The entry now points at the public search API host, with one method and two parameters. `guidestarindia.org` is registered as closed to automation instead of `crawl_allowed`.
- **api.github.com is now registered,** and closed except the repository's pinned contents path. Before this PR it was unclassified, and so readable wherever robots.txt allowed.
- **The research repository.** `org_grant_intelligence` replaces `hand_vetting_sheets` and is readable only at commit `414cd69…`, plus its pinned directory listing. Moving the pin is a registry change in a PR. The GitHub API allows about sixty unauthenticated calls an hour.
- **Enforcement in code:** the per-hop redirect check, `CHECK BLOCKED`, and the save- and promote-time guards.
- **`record_registry_check`** is on the supervisor only. It is staff only (checked against `users.is_staff`), takes its checker from the conversation, and needs an uploaded document of the same organisation. Any document type counts, because the Doc Vault UI sets none.
- **The self-named block hold.** Re-run `make staff-source` for the CSO workbook after merge so its sidecar is rebuilt under the new digest. Fix any reported block at its source.
- **The acceptance results**, per check, as counts and statuses only.

---

## Self-review

**Spec coverage.**

| Spec item | Task |
|---|---|
| C8: `give_do` and `guidestar_india` under `manual_aggregator`, allowed paths, `DISPATCHABLE` unchanged | 1, 2, 3 |
| C8: fetch tools refuse aggregator paths outside the list; values tagged `aggregator` / `claimed` | 3, 4, 5 |
| C9: `record_registry_check`, staff only, evidence document, never raises, cites, registered, named, labelled | 6, 7 |
| C10: the documents to request, listed in the skill | 9 |
| C12: `ngo-credential-research` rewritten per §4, generic | 9 |
| C14 / §4a: the repository in the registry as `internal_research`, pinned raw path only, others refused | 1, 2, 3 |
| §4a: read the dossier first, save as `prior_research` / `claimed`, re-fetch links, aggregators only under `manual_aggregator`, the primary source wins | 4 (banner), 5 (guard), 9 (skill), 10 (prompt), 7 (instructions) |
| §2 statuses: `applied`, `check_blocked`, `not_found` meanings | 3, 4, 5, 7, 9, 10 |
| §4 staff dataset note: a self-named block is held | 8 |
| Researcher prompt, entity-record, ngo-brief-for-funders, docs/SKILLS.md, docs/INGEST.md | 7, 10 |
| §5 acceptance run, plus C14's prior-research check | 11 |

**Ambiguities resolved here.**

1. **`give` is kept, not replaced.** A second entry on the same host would be dead under host-level strictness, so rules became path-aware (`rule_for_url`). `give_do` claims `/discover/`; everything else on give.do stays `no_scraping`.
2. **`guidestar_india` keeps its key but moves host.** It now points at the frappe API host with an exact path and two parameters (`keyword`, `page_no`, read from the endpoint's own error). `guidestarindia.org` gets a closed entry so it cannot read as unclassified.
3. **`hand_vetting_sheets` is replaced** by `org_grant_intelligence`, the whole repository at full SHA `414cd69…`. A second entry on `api.github.com` was added for pinned directory listings, because raw GitHub cannot list a folder and the dossier's file names are not known in advance.
4. **The finding field for the tier is assumed to be `evidence_tier`,** because `FindingBase.evidence` is already the quote. The column on the tables stays `evidence`. Task 1 stops if (d) chose otherwise.
5. **Refuse at save, hold at promote.** A mislabelled aggregator or dossier finding is refused at save so the model fixes it. A labelled finding whose concept has no tier fields (a funder-side partner from a dossier) saves, since research keeps every value, but is held at promotion until a primary source confirms it.
6. **Evidence for a manual check is any uploaded document of the same organisation,** because the vault UI cannot set `doc_type`. A later check of equal rank replaces an earlier one, and the reply names what it replaced. Two current identifiers of one type are refused rather than guessed between.
7. **CAPTCHA detection only fires on short pages,** so a long page with a reCAPTCHA in its contact form is still read. 401/403/429 and sign-in paths are always walls.
8. **The self-named block match is exact equality after `normalise_name`.** The block is held whole and rendered with no marker or names. A profile key changes the digest, so (c)'s sidecars rebuild.

**Placeholder scan.** Every code step carries the code. The two values a test could not pin in advance, the robots dates and the SHA, are given, and Task 2, Step 1 re-reads them. The acceptance run's CSO is deliberately not named. The person running it chooses it, and the checks are stated generically.

**Type and name consistency.**
- `rule_for_url`, `path_refusal`, `claims_path`, `path_scoped` and `PATH_SCOPED` are used the same way in Tasks 1–5.
- `blocked_page(…, readable_chars=…)` and `check_blocked_reply` are defined in Task 4 and used only there and in the hook.
- `source_guards.problems(…, at=…)` is used by `check_research` and `hold_at_promote`.
- `manual_checks.record(pool, org=, id_type=, status=, document_id=, note=, user_id=)` matches the tool's call.
- `held_blocks` returns `(sheet, column, count)` in Task 8's search, script and test.

**Known limits, stated rather than solved.**
- A finding that cites a GuideStar profile URL on `guidestarindia.org` is not forced to `aggregator`. The researcher cannot read one, so it would only arise from a fabricated citation.
- GitHub's unauthenticated limit of about sixty calls an hour bounds directory listings.
- `trafilatura` may drop tables from a Give.do page. Task 11, Check 9 and the researcher's summary show whether figures came through.
