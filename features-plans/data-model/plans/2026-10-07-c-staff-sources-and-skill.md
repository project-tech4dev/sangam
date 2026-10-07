# Staff-only CSR sources, layout profiles and the intake skill — Implementation Plan

> **For agentic workers:** REQUIRED: execute this plan with superpowers:subagent-driven-development — a fresh implementer subagent per task, a fresh reviewer subagent checking each task before the next starts, and a whole-branch review at the end. Do not use executing-plans or implement inline. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three confidential spreadsheets go into a private `staff-sources` bucket. Each file gets a private `documents` row. The Import researcher reads every sheet of every file through a declared **layout profile**, using one tool, `read_source_rows`. Rows come back normalised to rupees, and every row is cited. The `funder-intake-research` skill is rewritten generically: source order, the eligibility guideline, the classification rule and programme rows. The `ngo-credential-research` skill names the staff CSO workbook as a source.

**Architecture:** The pieces, in order of the data path:

- **Parser.** `app/ingest/source_layouts.py` is a pure parser, like `app/agent/tools/sql/validator.py`. It turns bytes plus a `LayoutProfile` into `SourceRow`s, or raises a `LayoutError` that names the sheet and cell. It handles three layouts: `table`, `blocks_by_column` and `sections_by_heading`.
- **Profiles.** These are JSON files under `app/ingest/data/source_layouts/`.
- **Upload.** A one-off staff script, `scripts/upload_staff_source.py` (`make staff-source`):
  - parses each workbook once, so an unprofiled sheet fails the upload loudly;
  - stores the workbook in `staff-sources`, plus a gzipped JSON-lines **sidecar** of its normalised rows;
  - inserts one private `documents` row per object.
- **Read path.** `app/ingest/staff_sources.py` lists the datasets (`repositories/documents.py`), finds a funder's aliases (`repositories/funders.py`), streams the sidecar and filters by name. It falls back to re-parsing the workbook when the sidecar is stale. It renders cited lines.
- **The tool.** `read_source_rows` in `app/ingest/tools/pipeline_tools.py` wraps that read path. It goes on the `entity-researcher` subagent.
- **Promotion.** It maps a finding that cites a staff dataset onto that dataset's existing private row. Facts promoted from any sheet are public like any other row (D14); only the files stay staff-only. It holds a finding that cites a staff dataset without its `[source:…]` marker, because then the fact cannot be traced to its sheet and cell.

**Tech Stack:** Python 3.12, openpyxl (new runtime dependency), psycopg 3, FastAPI, deepagents/LangGraph, Supabase Storage REST (`app/integrations/storage.py`), Postgres migrations (`db/migrations/*.sql`), Next.js (one label in `toolLabels.ts`), pytest (`asyncio_mode = "auto"`).

**Spec:** features-plans/data-model/2026-10-07-funder-model-consolidation.md (§4, §5; D8, D9, D11, D12, D13, D14)

## Global Constraints

- **This PR comes after PR (b).** It assumes all of the following exist:
  - `funders.aliases text[]`;
  - `funder_activity` with kinds `spend|footprint|partner|programme` and the columns `classified_by`, `classification_note` and `classification_confirmed`;
  - a `partner` finding with optional `amount` and `outlay` (`Money`), written to `funder_activity.amount` / `outlay` in rupees (plan (b) Task 11);
  - eligibility as a `documents` row with `doc_type = 'funder_eligibility'`;
  - `doc_type = 'source_dataset'` permitted wherever (b) constrains `doc_type`.

  If (b) added a CHECK on `documents.doc_type`, `'source_dataset'` must be in it. Verify with `\d+ documents` before Task 7.
- **PR #92 is already on master** (45e19f3, plus #97). Do not write "not merged" in the PR. What is enforced today:
  - `documents_read` RLS (0027) limits a row with `is_public = false` and `org_id IS NULL` to `app.is_staff()`;
  - `readable_document()` does the same for the download route;
  - the Import chat is behind `require_staff` / `staff_chat_access`;
  - agent tools still run as the owner (0027: "until step 8"), so for `read_source_rows` the gate is the staff-only Import route.

  The PR description says exactly this.
- **Confidentiality:**
  - The three real spreadsheets are never committed, copied into fixtures, logged, written to `content_md`, or chunked.
  - Every test fixture is generated in code, with invented names and numbers.
  - No real company, CSO or funder name, and no figure from the files, appears in code, tests, profiles, skills, docs or commit messages.
- **Tool conventions** (CLAUDE.md):
  - the tool never raises, and returns `read_source_rows failed: …` instead;
  - every row is cited, as `[source:<document_id>#<sheet>:<cell>]`;
  - the tool is registered, named in the prompt that owns it, and labelled in `frontend/features/ingest/lib/toolLabels.ts`.
- **No row content in any log line or error string.** A `LayoutError` names a sheet, a cell and a header text, never a data value.
- **`DISPATCHABLE` stays unchanged, and so does every `access_rule` in the source registry JSON.** The one registry edit is the `basis` text of `ffrh_funder_datasets` (Task 10, spec D14).
- **The files are staff-only; promoted facts are not (D14).** The workbooks, their sidecars and their `documents` rows are readable by staff alone. A fact a researcher saves from any sheet, with its marker, is promoted as a public row like any other. No sheet is withheld and none is labelled internal.
- **Schema changes go in `db/migrations/`, never `db/init/02_schema.sql`.** The migration is numbered after (b)'s; renumber it at merge if branches land in a different order.
- **Unit tests never touch a database.** Monkeypatch `repositories/` functions. Only tests marked `integration` use the compose Postgres.
- **Code style:** ruff, line length 110, py312. `cd backend && ruff check .` is clean after every task.
- **Commits:** every commit message ends with:

  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  ```

## Review Focus

Five failure modes the happy-path tests would miss. Each one has a test in the task that owns it.

1. **Repeated column names mis-mapped, or repeated figures summed.**
   - The analytics report has two `State` columns: column D is the filer's state, column P is the project's. A name-keyed map silently keeps one of them.
   - The four company-level figures repeat on every project line, so a naive sum triples them.
   - Tests: `test_two_state_columns_keep_their_own_meaning` and `test_header_drift_fails_loudly` (Task 3), and `test_company_figures_are_stated_once_per_company_year` (Task 3).
2. **Lakh / crore / rupee mix-ups.**
   - MCA sheets are in crore and the sections sheet is in lakh.
   - The blocks sheet is headed ₹, but its cells carry `"12.5 Lakhs"`, `"1.2Cr"`, `"4lakhs"`, `"3,50,000"`, `"Not disclosed"` and `"10,000 and materials"`.
   - A unit applied twice, or an unparseable value turned into 0, is a factor-of-10⁵ error.
   - Tests: the `parse_amount` table (Task 2), `test_a_cell_suffix_overrides_the_sheet_unit` (Task 4) and `test_amounts_are_lakh` (Task 5).
3. **A new sheet, heading or column silently skipped.**
   - A sheet with no profile entry is an error. So is a header the profile does not map, and so is an unknown sub-heading inside a section.
   - Tests: `test_a_sheet_without_a_profile_entry_is_an_error` (Task 3), `test_an_unknown_block_header_is_an_error` (Task 4), `test_an_unknown_section_heading_is_an_error` (Task 5), and `test_the_upload_refuses_an_unprofiled_sheet` (Task 8).
4. **Someone other than staff reads a staff dataset.** An org admin, a member, a steward or anon must not read one.
   - Tests:
     - `test_a_staff_dataset_reaches_only_staff`, for RLS (Task 7, integration);
     - `TestAStaffDatasetIsStaffOnly`, for `readable_document` (Task 7, integration);
     - `test_a_staff_object_on_a_public_row_is_never_signed`, for the route (Task 6);
     - `test_the_bucket_policy_is_staff_and_select_only` (Task 6);
     - `test_read_source_rows_is_the_researchers_not_the_supervisors` (Task 9).
5. **The raw files leak into fixtures, logs, `content_md` or a public `documents` row, or a promoted fact loses its trail to the sheet.**
   - The dataset row has no `content_md`: `test_the_dataset_row_holds_no_content` (Task 7).
   - Nothing is logged: `test_nothing_from_a_row_reaches_the_log` (Task 7).
   - No spreadsheet is tracked: `test_no_spreadsheet_is_tracked` (Task 12).
   - A finding citing a staff dataset without its sheet/cell marker is held, since its provenance stops at the file: `test_a_staff_finding_without_its_marker_is_held` (Task 10). A finding citing a CSO funder sheet with its marker is promoted like any other: `test_a_finding_citing_a_cso_funder_sheet_is_kept` (Task 10).
   - A staff URL never creates a public `documents` row: `test_a_document_finding_at_a_staff_url_adds_no_row` (Task 10).
   - Contact details are dropped at parse time: `test_contact_details_never_leave_the_parser` (Task 4).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `backend/pyproject.toml`, `backend/uv.lock` | modify | `openpyxl` runtime dependency (Task 1) |
| `backend/app/ingest/source_layouts.py` | create | Pure. Profile model and loading, normalisers, the three layout readers, `split_by_sheet`, `company_years` |
| `backend/app/ingest/data/source_layouts/mca_csr_analytics_report.json` | create | Profile: 11 per-year sheets, table, crore, D and P both `State` |
| `backend/app/ingest/data/source_layouts/mca_csr_dataful_subset.json` | create | Profile: one sheet, table, crore |
| `backend/app/ingest/data/source_layouts/cso_programmes_and_funders.json` | create | Profile: `CSO Profile` table, `CSO Funder Details` blocks, `CSO Current funder and Partners` sections |
| `backend/app/ingest/staff_sources.py` | create | Keys, the `.invalid` source URL, sidecar encode/decode with cache, `register_dataset`, `search` and rendering, `hold_unmarked` |
| `backend/app/repositories/documents.py` | modify | `insert_source_dataset`, `source_dataset_by_hash`, `list_source_datasets` |
| `backend/app/repositories/funders.py` | modify | `name_variants` |
| `backend/app/integrations/storage.py` | modify | `STAFF_SOURCES`, `BUCKETS`; `split()` learns the bucket |
| `backend/app/api/routes/documents.py` | modify | Never sign a staff-sources object on a public or org row |
| `db/migrations/0032_staff_sources_bucket.sql` | create | Private bucket plus a staff-only SELECT policy, guarded |
| `scripts/upload_staff_source.py` | create | Thin CLI over `staff_sources.register_dataset` |
| `Makefile` | modify | `staff-source` target (host venv, honours `ENV`) |
| `backend/app/ingest/tools/pipeline_tools.py` | modify | `read_source_rows` tool |
| `backend/app/ingest/agent.py` | modify | Register on `RESEARCH_TOOLS` |
| `backend/app/ingest/prompts/entity_researcher.md` | modify | Name the tool and its rules |
| `backend/app/ingest/instructions.md` | modify | Source priority line; "Tools you do NOT have" row |
| `backend/app/ingest/promote.py` | modify | Staff URLs map to the dataset row; a staff finding without its marker is held |
| `backend/app/ingest/data/sources/funders.json` | modify | `ffrh_funder_datasets.basis`: FFRH has cleared the figures for display (D14) |
| `frontend/features/ingest/lib/toolLabels.ts` | modify | Label |
| `backend/app/ingest/skills/funder-intake-research/SKILL.md` | rewrite | §4 "The skill" |
| `backend/app/ingest/skills/ngo-credential-research/SKILL.md` | modify | The staff CSO workbook as a source |
| `backend/tests/staff_source_fixtures.py` | create | Synthetic workbooks in all three shapes |
| `backend/tests/test_source_layouts.py` | create | Parser tests |
| `backend/tests/test_staff_sources.py` | create | Read path, tool, upload, promotion tests |
| `backend/tests/test_storage.py`, `test_vault.py`, `test_rls.py`, `test_harness.py`, `test_ingest.py` | modify | Bucket, route, RLS, tool-list pins |
| `docs/INGEST.md`, `docs/SKILLS.md`, `.gitignore` | modify | Docs; ignore `*.xlsx` |

---

### Task 1: `openpyxl` as a runtime dependency

**Files:**
- Modify: `backend/pyproject.toml`, `backend/uv.lock`
- Test: `backend/tests/test_source_layouts.py` (create)

**Interfaces:** none.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_source_layouts.py`:

```python
"""The staff-dataset reader: layout profiles, normalisers, and the three layouts.

Every workbook here is generated by tests/staff_source_fixtures.py. The real files are
confidential and never committed; the fixtures reproduce their shapes, not their contents.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_openpyxl_ships_with_the_backend():
    """#77 shipped a dependency the image never installed. The image installs from
    pyproject and Vercel resolves uv.lock, so both have to carry it."""
    deps = tomllib.loads((BACKEND / "pyproject.toml").read_text())["project"]["dependencies"]
    assert any(d.split(">")[0].split("=")[0].strip() == "openpyxl" for d in deps)
    assert 'name = "openpyxl"' in (BACKEND / "uv.lock").read_text()
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd backend && pytest tests/test_source_layouts.py -q`
Expected: `1 failed` (`assert False`).

- [ ] **Step 3: Add the dependency**

In `backend/pyproject.toml`, add this line after `"pypdf>=5",`:

```toml
    "openpyxl>=3.1",
```

Then run:

```bash
cd backend && uv lock && uv sync
```

Expected: `uv.lock` gains `name = "openpyxl"` and `name = "et-xmlfile"`.

- [ ] **Step 4: Run the test**

Run: `cd backend && pytest tests/test_source_layouts.py -q`
Expected: `1 passed`.

- [ ] **Step 5: Confirm the image installs it**

Run: `docker compose build backend && docker compose run --rm --no-deps backend python -c "import openpyxl; print(openpyxl.__version__)"`
Expected: a version string such as `3.1.5`.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/tests/test_source_layouts.py
git commit -m "build(backend): add openpyxl for the staff dataset reader

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The layout model, the normalisers and profile loading

**Files:**
- Create: `backend/app/ingest/source_layouts.py`
- Create: `backend/app/ingest/data/source_layouts/` (empty for now; it holds JSON from Task 3 on)
- Test: `backend/tests/test_source_layouts.py`

**Interfaces:**

```python
Layout = Literal["table", "blocks_by_column", "sections_by_heading"]
Unit = Literal["inr", "lakh", "crore"]
class LayoutError(ValueError): ...
@dataclass(frozen=True) class Money: rupees: Decimal | None; raw: str; unit: Unit
@dataclass(frozen=True) class ColumnRule: field: str; header: tuple[str, ...]; label: str; column: str | None
@dataclass(frozen=True) class TableSpec: heading: tuple[str, ...]; kind: str; columns: tuple[ColumnRule, ...]
@dataclass(frozen=True) class SheetProfile: ...   # see code
@dataclass(frozen=True) class LayoutProfile: name; source_key; filename_pattern; load; sheets; digest
@dataclass class SourceRow: sheet; cell; kind; text; money; fiscal_year; period; mode; details; context
def parse_amount(value: Any, unit: Unit) -> Money
def parse_fiscal_year(value: Any) -> tuple[str | None, str | None]   # (FY2023-24, None) or (None, raw period)
def parse_mode(value: Any) -> str                                      # one of MODES
def normalise_name(value: Any) -> str
def search_terms(names: Iterable[str]) -> list[str]
def name_matches(name: str, terms: list[str]) -> bool
def parse_profile(raw: dict[str, Any]) -> LayoutProfile
def load_profiles() -> dict[str, LayoutProfile]
def profile_for(source_key: str, filename: str) -> LayoutProfile
def profile_from_version(extractor_version: str) -> LayoutProfile
def iter_rows(data: bytes, profile: LayoutProfile) -> Iterator[SourceRow]
def read_rows(data: bytes, profile: LayoutProfile) -> list[SourceRow]
```

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_source_layouts.py`:

```python
from decimal import Decimal

import pytest

from app.ingest import source_layouts as layouts
from app.ingest.source_layouts import LayoutError, parse_amount, parse_fiscal_year, parse_mode


@pytest.mark.parametrize(
    "value, unit, rupees, used",
    [
        (0.13, "crore", Decimal("1300000"), "crore"),
        ("6.38\n", "crore", Decimal("63800000"), "crore"),          # trailing newline in a number
        ("0.00", "crore", Decimal("0"), "crore"),                    # filed zero stays zero
        (25, "lakh", Decimal("2500000"), "lakh"),
        (7.5, "lakh", Decimal("750000"), "lakh"),
        (450000, "inr", Decimal("450000"), "inr"),
        ("3,50,000", "inr", Decimal("350000"), "inr"),               # Indian digit grouping
        ("12.5 Lakhs", "inr", Decimal("1250000"), "lakh"),           # the cell's unit wins
        ("4lakhs", "inr", Decimal("400000"), "lakh"),
        ("22.5lakh", "inr", Decimal("2250000"), "lakh"),
        ("1.2Cr", "inr", Decimal("12000000"), "crore"),
        ("3 crore", "lakh", Decimal("30000000"), "crore"),
    ],
)
def test_amounts_become_rupees(value, unit, rupees, used):
    money = parse_amount(value, unit)
    assert money.rupees == rupees
    assert money.unit == used


@pytest.mark.parametrize(
    "value", ["Nec/ Not Mentioned", "NEC/ Not Mentioned", "Not disclosed", "-", "",
              "10,000 and materials", "9,99.99,999", "(included in expenditure)", None, -5],
)
def test_an_amount_that_is_not_a_number_is_None_never_zero(value):
    money = parse_amount(value, "inr")
    assert money.rupees is None
    assert money.raw == ("" if value is None else str(value).strip())


@pytest.mark.parametrize(
    "value, fy, period",
    [
        ("2023-24", "FY2023-24", None),
        ("FY2023-24", "FY2023-24", None),
        ("2024–25", "FY2024-25", None),                    # en dash
        ("2021-23", None, "2021-23"),                      # two years is a period
        ("2022-2025 (Closed)", None, "2022-2025 (Closed)"),
        ("2021–2024", None, "2021–2024"),
        ("Post 2022", None, "Post 2022"),
        (2023, None, "2023"),
        (None, None, None),
    ],
)
def test_only_one_exact_fiscal_year_becomes_a_fiscal_year(value, fy, period):
    assert parse_fiscal_year(value) == (fy, period)


@pytest.mark.parametrize(
    "value, mode",
    [
        ("Directly by Company", "direct"),
        ("Directly by company", "direct"),
        ("Other Implementing agencies", "implementing_agency"),
        ("By Trusts/Societies/ Section 8 company set up by company itself", "own_trust_or_section8"),
        ("By Trusts/Societies/Section 8 company set up by Central or State Government or entities "
         "established", "implementing_agency"),
        ("NEC/ Not Mentioned", "not_stated"),
        ("Nec/ Not Mentioned", "not_stated"),
        (None, "not_stated"),
    ],
)
def test_implementation_mode_maps_onto_the_four_values(value, mode):
    assert parse_mode(value) == mode


def test_names_match_on_whole_words_ignoring_legal_suffixes():
    terms = layouts.search_terms(["Kestrel Polymers Ltd.", "kestrel"])
    assert terms == ["kestrel polymers", "kestrel"]
    assert layouts.name_matches("KESTREL POLYMERS LIMITED", terms)
    assert layouts.name_matches("Kestrel Foundation", terms)
    assert not layouts.name_matches("Kestrelworks Private Limited", ["kestrel"])


def test_a_term_under_three_letters_is_dropped():
    assert layouts.search_terms(["AB", "The Ltd"]) == []


def _minimal(**sheet):
    base = {"layout": "table", "sheet": "S", "amount_unit": "crore",
            "columns": [{"column": "A", "header": "Name", "field": "company"}]}
    return {"name": "x", "source_key": "mca_csr", "filename_pattern": "x", "sheets": [{**base, **sheet}]}


def test_a_profile_with_an_unknown_field_is_refused():
    with pytest.raises(LayoutError, match="unknown field"):
        layouts.parse_profile(_minimal(columns=[{"column": "A", "header": "N", "field": "ceo"}]))


def test_a_table_column_needs_its_letter():
    with pytest.raises(LayoutError, match="needs its letter"):
        layouts.parse_profile(_minimal(columns=[{"header": "N", "field": "company"}]))


def test_blocks_and_sections_need_the_full_workbook():
    raw = _minimal(layout="blocks_by_column", block_start_header=["Funder"],
                   columns=[{"header": "Funder", "field": "funder"}])
    with pytest.raises(LayoutError, match='"load": "full"'):
        layouts.parse_profile(raw)


def test_the_digest_changes_when_the_profile_does():
    a = layouts.parse_profile(_minimal())
    b = layouts.parse_profile(_minimal(amount_unit="lakh"))
    assert a.digest != b.digest and len(a.digest) == 8


def test_every_shipped_profile_parses_and_names_a_registered_source():
    from app.ingest.sources import SOURCES

    for name, profile in layouts.load_profiles().items():
        assert profile.name == name
        assert profile.source_key in SOURCES, name
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_source_layouts.py -q`
Expected: `ModuleNotFoundError: No module named 'app.ingest.source_layouts'`.

- [ ] **Step 3: Write the module**

Create `backend/app/ingest/data/source_layouts/.gitkeep` (empty). Then create `backend/app/ingest/source_layouts.py`:

```python
"""Layout profiles for the staff datasets, and the reader that applies them.

Pure, like app/agent/tools/sql/validator.py: no pool, no async, no settings, no
storage. Bytes and a profile in; normalised rows out, or a LayoutError that names
the sheet and the cell (never a value from a data row - these files are confidential).

Three shapes (spec D13):

  table                one header row, one record per row. A column is named by its
                       letter AND its header, so two columns both called "State"
                       cannot swap, and a header that moved fails loudly.
  blocks_by_column     side-by-side blocks, one per organisation, its name in a title
                       row above the block's own header.
  sections_by_heading  one section per organisation under a numbered heading, each
                       holding one or more headed sub-tables.

A sheet with no entry in the profile is an error, not a skip: a new sheet in a
re-uploaded workbook must stop the read, not vanish from it.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from importlib.resources import files
from typing import Any, Literal

from openpyxl import Workbook, load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

Layout = Literal["table", "blocks_by_column", "sections_by_heading"]
Unit = Literal["inr", "lakh", "crore"]

LAYOUTS: tuple[str, ...] = ("table", "blocks_by_column", "sections_by_heading")
RUPEES_PER: dict[str, Decimal] = {"inr": Decimal(1), "lakh": Decimal(100_000), "crore": Decimal(10_000_000)}

# The spec's twelve normalised fields, plus what these files hold that has somewhere to go.
FIELDS: frozenset[str] = frozenset({
    "company", "funder", "cso", "fiscal_year", "project", "filed_sector", "state", "district",
    "outlay", "amount", "implementation_mode", "purpose",
    # MCA: the filer's own state, and the four company-level figures every project line repeats
    "company_state", "avg_net_profit", "prescribed_csr", "csr_spent", "local_area_spent",
    # the recipient side
    "funder_type", "partner", "role",
    # kept under its header as printed, or declared and dropped
    "detail", "omit",
})
MONEY_FIELDS: frozenset[str] = frozenset(
    {"outlay", "amount", "avg_net_profit", "prescribed_csr", "csr_spent", "local_area_spent"}
)
COMPANY_YEAR_FIELDS: tuple[str, ...] = ("avg_net_profit", "prescribed_csr", "csr_spent", "local_area_spent")
NAME_FIELDS: tuple[str, ...] = ("company", "funder", "cso")
MODES: tuple[str, ...] = ("direct", "implementing_agency", "own_trust_or_section8", "not_stated")

NOT_STATED = re.compile(
    r"^(?:nec\s*/\s*not mentioned|not mentioned|not disclosed|not available|n/?a|nil|-+|–|—)$", re.I
)
_NUMBER = r"(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?"
_PLAIN = re.compile(rf"^{_NUMBER}$")
_SUFFIXED = re.compile(rf"^(?P<num>{_NUMBER})\s*(?P<unit>lakhs?|lacs?|crores?|cr)\.?$", re.I)
_FY = re.compile(r"^(?:FY\s*)?(\d{4})\s*[-–]\s*(\d{2})$", re.I)
_LEGAL_WORDS = re.compile(r"\b(?:the|limited|ltd|private|pvt)\b")


class LayoutError(ValueError):
    """The workbook does not match its profile, or a profile is malformed."""


# --- values -------------------------------------------------------------------


@dataclass(frozen=True)
class Money:
    """An amount in rupees, with the figure as printed and the unit that was applied."""

    rupees: Decimal | None
    raw: str
    unit: Unit

    def to_json(self) -> dict[str, Any]:
        return {"rupees": None if self.rupees is None else str(self.rupees), "raw": self.raw, "unit": self.unit}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Money:
        return cls(None if d["rupees"] is None else Decimal(d["rupees"]), d["raw"], d["unit"])


def _norm(value: Any) -> str:
    """A header for comparison: whitespace (newlines included) collapsed, casefolded."""
    return " ".join(str("" if value is None else value).split()).casefold()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def to_rupees(value: Decimal, unit: Unit) -> Decimal:
    rupees = value * RUPEES_PER[unit]
    return rupees.quantize(Decimal(1)) if rupees == rupees.to_integral_value() else rupees.quantize(
        Decimal("0.01")
    )


def parse_amount(value: Any, unit: Unit) -> Money:
    """Rupees, or None with the printed text kept. Never 0 for something that is not a number.

    `unit` is the sheet's; a suffix in the cell ("12.5 Lakhs", "1.2Cr") overrides it, which
    is the only way one column can hold rupees and lakhs at once and still read right.
    """
    if value is None or isinstance(value, bool):
        return Money(None, "" if value is None else str(value), unit)
    if isinstance(value, (int, float)):
        if value < 0:
            return Money(None, str(value), unit)
        return Money(to_rupees(Decimal(str(value)), unit), str(value), unit)
    raw = str(value).strip()
    if not raw or NOT_STATED.match(raw):
        return Money(None, raw, unit)
    suffixed = _SUFFIXED.match(raw)
    if suffixed:
        cell_unit: Unit = "crore" if suffixed["unit"].lower().startswith("cr") else "lakh"
        return Money(to_rupees(Decimal(suffixed["num"].replace(",", "")), cell_unit), raw, cell_unit)
    if _PLAIN.match(raw):
        return Money(to_rupees(Decimal(raw.replace(",", "")), unit), raw, unit)
    return Money(None, raw, unit)


def parse_fiscal_year(value: Any) -> tuple[str | None, str | None]:
    """(FY2023-24, None) for exactly one Indian fiscal year; (None, the text) for anything else.

    A range, an open-ended "(Ongoing)" or "Post 2022" is a period, kept as printed. Turning
    one into a fiscal year would be a guess, and research_records refuses guessed years.
    """
    raw = _text(value)
    if raw is None:
        return None, None
    m = _FY.match(raw)
    if m and int(m[2]) == (int(m[1]) + 1) % 100:
        return f"FY{m[1]}-{m[2]}", None
    return None, raw


def parse_mode(value: Any) -> str:
    """The filed implementation mode as one of MODES. The filed wording is kept separately.

    "Set up by Central or State Government" is an agency the company did not set up, so it is
    an implementing agency, not the company's own trust.
    """
    text = _norm(value)
    if not text or NOT_STATED.match(text):
        return "not_stated"
    if text.startswith("directly"):
        return "direct"
    if "set up by company itself" in text:
        return "own_trust_or_section8"
    if "implementing agenc" in text or "set up by central or state government" in text:
        return "implementing_agency"
    return "not_stated"


def normalise_name(value: Any) -> str:
    text = str(value or "").casefold().replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)
    text = _LEGAL_WORDS.sub(" ", text)
    return " ".join(text.split())


def search_terms(names: Iterable[str]) -> list[str]:
    out: list[str] = []
    for name in names:
        term = normalise_name(name)
        if len(term) >= 3 and term not in out:
            out.append(term)
    return out


def name_matches(name: str, terms: list[str]) -> bool:
    padded = f" {normalise_name(name)} "
    return any(f" {t} " in padded for t in terms)


# --- rows ---------------------------------------------------------------------


@dataclass
class SourceRow:
    """One record from one sheet, normalised. `cell` is the record's first cell, e.g. "AQ14":
    side-by-side blocks share row numbers, so a row number alone would not cite one."""

    sheet: str
    cell: str
    kind: str
    text: dict[str, str] = field(default_factory=dict)
    money: dict[str, Money] = field(default_factory=dict)
    fiscal_year: str | None = None
    period: str | None = None
    mode: str | None = None
    details: dict[str, str] = field(default_factory=dict)
    context: dict[str, str] = field(default_factory=dict)

    def names(self) -> list[str]:
        return [self.text[f] for f in NAME_FIELDS if self.text.get(f)]

    def search_key(self) -> str:
        """Padded, so a byte search for " term " finds whole words inside the JSON line."""
        return " " + " | ".join(normalise_name(n) for n in self.names()) + " "

    def to_json(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet, "cell": self.cell, "kind": self.kind,
            "text": self.text, "money": {k: m.to_json() for k, m in self.money.items()},
            "fiscal_year": self.fiscal_year, "period": self.period, "mode": self.mode,
            "details": self.details, "context": self.context, "k": self.search_key(),
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> SourceRow:
        return cls(
            sheet=d["sheet"], cell=d["cell"], kind=d["kind"], text=d["text"],
            money={k: Money.from_json(m) for k, m in d["money"].items()},
            fiscal_year=d["fiscal_year"], period=d["period"], mode=d["mode"],
            details=d["details"], context=d["context"],
        )


# --- profiles -----------------------------------------------------------------


@dataclass(frozen=True)
class ColumnRule:
    field: str
    header: tuple[str, ...]          # accepted header texts, normalised
    label: str                       # the first header as printed, for `detail`
    column: str | None = None        # the letter, for table and section layouts


@dataclass(frozen=True)
class TableSpec:
    heading: tuple[str, ...]
    kind: str
    columns: tuple[ColumnRule, ...]


@dataclass(frozen=True)
class SheetProfile:
    layout: Layout
    amount_unit: Unit
    kind: str = "line"
    sheet: str | None = None
    sheet_pattern: str | None = None
    header_row: int = 1
    title_row: int | None = None
    block_start_header: tuple[str, ...] = ()
    section_pattern: str | None = None
    note_cell: str | None = None
    title_field: str | None = None
    columns: tuple[ColumnRule, ...] = ()
    tables: tuple[TableSpec, ...] = ()
    codes: dict[str, dict[str, str]] = field(default_factory=dict, hash=False, compare=False)

    def matches(self, name: str) -> bool:
        if self.sheet is not None:
            return name == self.sheet
        return re.fullmatch(self.sheet_pattern or "", name) is not None


@dataclass(frozen=True)
class LayoutProfile:
    name: str
    source_key: str
    filename_pattern: str
    load: Literal["read_only", "full"]
    sheets: tuple[SheetProfile, ...]
    digest: str

    @property
    def stored_name(self) -> str:
        return f"{self.name}.xlsx"

    @property
    def version(self) -> str:
        """What documents.extractor_version records: which profile, at which revision."""
        return f"source_layouts/{self.name}@{self.digest}"

    def sheet_for(self, name: str) -> SheetProfile:
        found = [s for s in self.sheets if s.matches(name)]
        if not found:
            raise LayoutError(
                f"sheet {name!r} has no entry in source_layouts/{self.name}.json - add one before "
                f"this file can be read"
            )
        if len(found) > 1:
            raise LayoutError(f"sheet {name!r} matches {len(found)} entries in source_layouts/{self.name}.json")
        return found[0]


def _rule(raw: dict[str, Any], *, positional: bool, where: str) -> ColumnRule:
    fld = raw.get("field")
    if fld not in FIELDS:
        raise LayoutError(f"{where}: unknown field {fld!r}")
    header = raw.get("header")
    headers = (header,) if isinstance(header, str) else tuple(header or ())
    if not headers:
        raise LayoutError(f"{where}: the {fld!r} column needs its header text")
    column = raw.get("column")
    if positional and not column:
        raise LayoutError(f"{where}: the {fld!r} column needs its letter")
    if column:
        try:
            column_index_from_string(column)
        except ValueError as exc:
            raise LayoutError(f"{where}: {column!r} is not a column letter") from exc
    return ColumnRule(field=fld, header=tuple(_norm(h) for h in headers), label=" ".join(headers[0].split()),
                      column=column)


def parse_profile(raw: dict[str, Any]) -> LayoutProfile:
    name = raw["name"]
    sheets: list[SheetProfile] = []
    for i, s in enumerate(raw["sheets"]):
        where = f"source_layouts/{name}.json sheets[{i}]"
        layout = s.get("layout")
        if layout not in LAYOUTS:
            raise LayoutError(f"{where}: layout must be one of {', '.join(LAYOUTS)}")
        if ("sheet" in s) == ("sheet_pattern" in s):
            raise LayoutError(f"{where}: give exactly one of sheet, sheet_pattern")
        if s.get("amount_unit") not in RUPEES_PER:
            raise LayoutError(f"{where}: amount_unit must be inr, lakh or crore")
        positional = layout != "blocks_by_column"
        columns = tuple(_rule(c, positional=positional, where=where) for c in s.get("columns", ()))
        tables = tuple(
            TableSpec(
                heading=tuple(_norm(h) for h in t["heading"]), kind=t["kind"],
                columns=tuple(_rule(c, positional=True, where=where) for c in t["columns"]),
            )
            for t in s.get("tables", ())
        )
        if layout == "sections_by_heading" and not (tables and s.get("section_pattern")):
            raise LayoutError(f"{where}: a sections layout needs section_pattern and tables")
        if layout != "sections_by_heading" and not columns:
            raise LayoutError(f"{where}: no columns")
        if layout == "blocks_by_column" and not s.get("block_start_header"):
            raise LayoutError(f"{where}: a blocks layout needs block_start_header")
        for group in (columns, *(t.columns for t in tables)):
            letters = [c.column for c in group if c.column]
            if len(set(letters)) != len(letters):
                raise LayoutError(f"{where}: a column letter is mapped twice")
        sheets.append(SheetProfile(
            layout=layout, amount_unit=s["amount_unit"], kind=s.get("kind", "line"),
            sheet=s.get("sheet"), sheet_pattern=s.get("sheet_pattern"),
            header_row=s.get("header_row", 1), title_row=s.get("title_row"),
            block_start_header=tuple(_norm(h) for h in s.get("block_start_header", ())),
            section_pattern=s.get("section_pattern"), note_cell=s.get("note_cell"),
            title_field=s.get("title_field"), columns=columns, tables=tables,
            codes=s.get("codes", {}),
        ))
    load = raw.get("load", "read_only")
    if load not in ("read_only", "full"):
        raise LayoutError(f"source_layouts/{name}.json: load must be read_only or full")
    if load == "read_only" and any(s.layout != "table" for s in sheets):
        raise LayoutError(
            f'source_layouts/{name}.json: blocks and sections need merged cells; set "load": "full"'
        )
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:8]
    return LayoutProfile(name=name, source_key=raw["source_key"], filename_pattern=raw["filename_pattern"],
                         load=load, sheets=tuple(sheets), digest=digest)


def load_profiles() -> dict[str, LayoutProfile]:
    folder = files("app.ingest") / "data" / "source_layouts"
    out: dict[str, LayoutProfile] = {}
    for entry in folder.iterdir():
        if not entry.name.endswith(".json"):
            continue
        profile = parse_profile(json.loads(entry.read_text(encoding="utf-8")))
        if profile.name != entry.name.removesuffix(".json"):
            raise LayoutError(f"{entry.name}: name {profile.name!r} must equal the file name")
        out[profile.name] = profile
    return out


def profile_for(source_key: str, filename: str) -> LayoutProfile:
    """The one profile for an uploaded file, by its registry key and its original file name."""
    found = [p for p in load_profiles().values()
             if p.source_key == source_key and re.search(p.filename_pattern, filename)]
    if len(found) != 1:
        raise LayoutError(
            f"{len(found)} layout profiles for {source_key} match this file name; exactly one must - "
            f"add or narrow one in backend/app/ingest/data/source_layouts/"
        )
    return found[0]


def profile_from_version(extractor_version: str | None) -> LayoutProfile:
    """The profile a documents row was uploaded under, at its current revision."""
    m = re.fullmatch(r"source_layouts/(?P<name>[\w-]+)@[0-9a-f]{8}", extractor_version or "")
    profiles = load_profiles()
    if m is None or m["name"] not in profiles:
        raise LayoutError(f"no layout profile named by extractor_version {extractor_version!r}")
    return profiles[m["name"]]


# --- reading ------------------------------------------------------------------

Reader = Callable[[Any, str, SheetProfile], Iterator[SourceRow]]
_READERS: dict[str, Reader] = {}


def _row(
    sheet: str, cell: str, spec: SheetProfile, kind: str, cells: list[tuple[ColumnRule, Any]], *,
    context: dict[str, str] | None = None, fixed: dict[str, str | None] | None = None,
) -> SourceRow | None:
    """One SourceRow from (rule, value) pairs, or None when every mapped cell is empty."""
    row = SourceRow(sheet=sheet, cell=cell, kind=kind, context=dict(context or {}))
    seen = False
    for rule, value in cells:
        if rule.field == "omit":
            continue
        if _text(value) is not None:
            seen = True
        if rule.field in MONEY_FIELDS:
            row.money[rule.field] = parse_amount(value, spec.amount_unit)
        elif rule.field == "fiscal_year":
            row.fiscal_year, row.period = parse_fiscal_year(value)
        elif rule.field == "detail":
            text = _text(value)
            if text is not None:
                row.details[rule.label] = text
        else:
            if rule.field == "implementation_mode":
                row.mode = parse_mode(value)
            text = _text(value)
            if text is None or NOT_STATED.match(text):
                continue
            decoded = spec.codes.get(rule.field, {}).get(text)
            row.text[rule.field] = f"{decoded} ({text})" if decoded else text
    if not seen:
        return None
    for key, value in (fixed or {}).items():
        if value:
            row.text[key] = value
    return row


def _check_header(sheet: str, row_number: int, header: tuple[Any, ...], rules: Iterable[ColumnRule]) -> None:
    """Every mapped column reads its expected header, and no header goes unmapped."""
    claimed: set[int] = set()
    for rule in rules:
        i = column_index_from_string(rule.column) - 1
        claimed.add(i)
        found = _norm(header[i]) if i < len(header) else ""
        if found not in rule.header:
            raise LayoutError(
                f"sheet {sheet!r} row {row_number}: column {rule.column} reads {found!r}; the profile "
                f"expects {' or '.join(map(repr, rule.header))} for {rule.field}"
            )
    extra = [get_column_letter(i + 1) for i, v in enumerate(header) if i not in claimed and _norm(v)]
    if extra:
        raise LayoutError(
            f"sheet {sheet!r} row {row_number}: column(s) {', '.join(extra)} have a header the profile "
            f"does not map - add them, as 'omit' if they are not wanted"
        )


def iter_rows(data: bytes, profile: LayoutProfile) -> Iterator[SourceRow]:
    """Every row of every sheet. Every sheet is matched to its entry before any is read,
    so a workbook with one unprofiled sheet fails before it yields a row."""
    book = load_workbook(io.BytesIO(data), read_only=profile.load == "read_only", data_only=True)
    try:
        plan = [(ws, profile.sheet_for(ws.title)) for ws in book.worksheets]
        for ws, spec in plan:
            yield from _READERS[spec.layout](ws, ws.title, spec)
    finally:
        book.close()


def read_rows(data: bytes, profile: LayoutProfile) -> list[SourceRow]:
    return list(iter_rows(data, profile))


def company_years(rows: Iterable[SourceRow]) -> list[SourceRow]:
    """One row per (sheet, company, fiscal year) that carries company-level figures.

    A filing repeats the company's obligation and spend on every project line; three
    project lines are one company-year, never three.
    """
    seen: dict[tuple[str, str, str | None], SourceRow] = {}
    for row in rows:
        if any(f in row.money for f in COMPANY_YEAR_FIELDS):
            seen.setdefault((row.sheet, normalise_name(row.text.get("company")), row.fiscal_year), row)
    return list(seen.values())


def split_by_sheet(data: bytes) -> list[tuple[str, bytes]]:
    """One workbook per sheet, values only. For a table-layout file over the bucket limit:
    every sheet keeps its own name, so the same profile reads each part."""
    source = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts: list[tuple[str, bytes]] = []
    try:
        for ws in source.worksheets:
            book = Workbook(write_only=True)
            out = book.create_sheet(ws.title)
            for values in ws.iter_rows(values_only=True):
                out.append(list(values))
            buffer = io.BytesIO()
            book.save(buffer)
            parts.append((ws.title, buffer.getvalue()))
    finally:
        source.close()
    return parts
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && pytest tests/test_source_layouts.py -q`
Expected: all pass. `test_every_shipped_profile_parses…` passes vacuously because the folder holds only `.gitkeep`.

- [ ] **Step 5: Lint and commit**

```bash
cd backend && ruff check app/ingest/source_layouts.py tests/test_source_layouts.py
git add backend/app/ingest/source_layouts.py backend/app/ingest/data/source_layouts/.gitkeep backend/tests/test_source_layouts.py
git commit -m "feat(ingest): layout profiles and normalisers for staff datasets

Rupees from crore, lakh or a per-cell suffix; a value that is not a number is None,
never zero. Only an exact YYYY-YY becomes a fiscal year.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The `table` layout and the two MCA profiles

**Files:**
- Create: `backend/tests/staff_source_fixtures.py`
- Create: `backend/app/ingest/data/source_layouts/mca_csr_analytics_report.json`, `mca_csr_dataful_subset.json`
- Modify: `backend/app/ingest/source_layouts.py` (add `_read_table`)
- Test: `backend/tests/test_source_layouts.py`

**Interfaces:**

```python
def _read_table(ws, name: str, spec: SheetProfile) -> Iterator[SourceRow]   # registered as _READERS["table"]
# fixtures
def analytics_report(*, extra_sheet: str | None = None, header: list[str] | None = None) -> bytes
def dataful_subset() -> bytes
ANALYTICS_NAME = "CSR Analytics Report FY2014-2025 (synthetic).xlsx"
DATAFUL_NAME = "Dataful subset (synthetic).xlsx"
```

- [ ] **Step 1: Write the fixture builders**

Create `backend/tests/staff_source_fixtures.py`:

```python
"""Synthetic workbooks in the three staff-dataset layouts.

Every name and number here is invented. The real files are confidential and are never
committed (test_no_spreadsheet_is_tracked). These reproduce their SHAPES - repeated column
names, side-by-side blocks, headed sections, lakh against crore, trailing newlines in numbers -
and nothing else.
"""

from __future__ import annotations

import io
import re

from openpyxl import Workbook

ANALYTICS_NAME = "CSR Analytics Report FY2014-2025 (synthetic).xlsx"
DATAFUL_NAME = "Dataful subset (synthetic).xlsx"
CSO_NAME = "Details of programs and current funders (synthetic).xlsx"

ANALYTICS_HEADER = [
    "Year", "Company Name", "Class", "State", "Company Type", "RoC", "Sub Category", "Listing Status",
    "Average Net Profit", "CSR Prescribed Expenditure", "CSR Spent", "Local Area Spent", "S_No",
    "CSR_Project_s", "Development_Sector_s", "State", "District", "Project_Amount_Outlay_INR_Cr",
    "Amount_Spent_INR_Cr", "Mode_of_Implementation",
]
DATAFUL_HEADER = [
    "Group Company", "Subsidiary / Entity (MCA Filer Name)", "Fiscal Year", "State", "District", "Sector",
    "CSR Project Name", "Implementation Mode", "Project Amount Outlay (₹ Cr)", "Amount Spent (₹ Cr)", "Notes",
]


def _bytes(book: Workbook) -> bytes:
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _line(year, company, project, sector, state, district, outlay, spent, mode, *, company_state="Gujarat",
          anp="12.50\n", prescribed=0.25, csr_spent=0.3, local=0.1, serial="1."):
    return [year, company, "Public", company_state, "Other than Govt. Companies", "ROC-NOWHERE",
            "Company limited by Shares", "Unlisted", anp, prescribed, csr_spent, local, serial, project,
            sector, state, district, outlay, spent, mode]


def analytics_report(*, extra_sheet: str | None = None, header: list[str] | None = None) -> bytes:
    """Two year sheets. Kestrel files three project lines in 2023-24: its own state (D) is
    Gujarat, two of its projects' (P) are Odisha, so a swapped State column shows."""
    book = Workbook()
    book.remove(book.active)
    sheets = {
        "2022-23": [
            _line("2022-23", "Kestrel Polymers Limited", "School Kitchens", "Education", "Odisha",
                  "Nec/ Not Mentioned", 0.2, 0.2, "Directly by Company", anp="10.00", prescribed=0.2,
                  csr_spent=0.2, local=0.0),
        ],
        "2023-24": [
            _line("2023-24", "Kestrel Polymers Limited", "Rural Schools", "Education", "Odisha", "Northfield",
                  "0.12", "0.12", "Other Implementing agencies"),
            _line("2023-24", "Kestrel Polymers Limited", "Clean Water", "Health Care", "Odisha",
                  "Nec/ Not Mentioned", "Nec/ Not Mentioned", 0.08, "NEC/ Not Mentioned", serial="2."),
            _line("2023-24", "Kestrel Polymers Limited", "Skills Centre", "Livelihood Enhancement Projects",
                  "Gujarat", "Southmere", 0.1, "0.10\n",
                  "By Trusts/Societies/ Section 8 company set up by company itself", serial="3."),
            _line("2023-24", "Wren Textiles Private Limited", "Flood Relief", "Disaster Management", "Assam",
                  "Nec/ Not Mentioned", 0.05, 0.05, "Directly by company", company_state="Assam"),
        ],
    }
    for title, rows in sheets.items():
        ws = book.create_sheet(title)
        ws.append(header or ANALYTICS_HEADER)
        for row in rows:
            ws.append(row)
    if extra_sheet:
        # A year-shaped name gets the real header (a new year re-uploaded); anything else does not.
        is_year = re.fullmatch(r"\d{4}-\d{2}", extra_sheet) is not None
        book.create_sheet(extra_sheet).append(ANALYTICS_HEADER if is_year else ["Summary", "of", "everything"])
    return _bytes(book)


def dataful_subset() -> bytes:
    book = Workbook()
    ws = book.active
    ws.title = "Sheet1"
    ws.append(DATAFUL_HEADER)
    ws.append(["Kestrel", "Kestrel Polymers Limited", "2023-24", "Odisha", "Northfield", "Education",
               "Rural Schools", "Other Implementing agencies", 0.12, 0.12, None])
    ws.append(["Kestrel", "Kestrel Foundation", "2023-24", "Nec/ Not Mentioned",
               "District Not Classified Elsewhere", "Nec/ Not Mentioned", None, "Nec/ Not Mentioned",
               0.0, 0.0, "filed late"])
    ws.append(["Wren", "Wren Textiles Private Limited", "2023-24", "Assam", "Eastvale", "Disaster Management",
               "Flood Relief", "Directly by company", 0.05, 0.05, None])
    return _bytes(book)
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_source_layouts.py`:

```python
from tests.staff_source_fixtures import ANALYTICS_HEADER, ANALYTICS_NAME, DATAFUL_NAME, analytics_report, \
    dataful_subset


def _analytics():
    return layouts.profile_for("mca_csr", ANALYTICS_NAME)


def _kestrel_2023(rows):
    return [r for r in rows if r.sheet == "2023-24" and r.text.get("company") == "Kestrel Polymers Limited"]


def test_the_profile_is_found_by_key_and_file_name():
    assert _analytics().name == "mca_csr_analytics_report"
    assert layouts.profile_for("mca_csr", DATAFUL_NAME).name == "mca_csr_dataful_subset"
    with pytest.raises(LayoutError):
        layouts.profile_for("ffrh_funder_datasets", ANALYTICS_NAME)


def test_every_sheet_is_read():
    rows = layouts.read_rows(analytics_report(), _analytics())
    assert {r.sheet for r in rows} == {"2022-23", "2023-24"}
    assert len(rows) == 5


def test_two_state_columns_keep_their_own_meaning():
    first = _kestrel_2023(layouts.read_rows(analytics_report(), _analytics()))[0]
    assert first.text["company_state"] == "Gujarat"     # column D, the filer
    assert first.text["state"] == "Odisha"              # column P, the project
    assert first.text["district"] == "Northfield"


def test_project_lines_normalise():
    a, b, c = _kestrel_2023(layouts.read_rows(analytics_report(), _analytics()))
    assert (a.cell, a.fiscal_year, a.mode) == ("A2", "FY2023-24", "implementing_agency")
    assert a.text["implementation_mode"] == "Other Implementing agencies"
    assert a.money["amount"].rupees == Decimal("1200000") and a.money["amount"].raw == "0.12"
    assert b.money["outlay"].rupees is None and b.money["outlay"].raw == "Nec/ Not Mentioned"
    assert "district" not in b.text and b.mode == "not_stated"
    assert c.money["amount"].rupees == Decimal("1000000")              # "0.10\n"
    assert c.mode == "own_trust_or_section8"
    assert a.money["avg_net_profit"].rupees == Decimal("125000000")    # "12.50\n" crore


def test_company_figures_are_stated_once_per_company_year():
    rows = layouts.read_rows(analytics_report(), _analytics())
    years = [r for r in layouts.company_years(rows) if r.text["company"] == "Kestrel Polymers Limited"]
    assert [(r.sheet, r.fiscal_year) for r in years] == [("2022-23", "FY2022-23"), ("2023-24", "FY2023-24")]
    assert years[1].money["csr_spent"].rupees == Decimal("3000000")   # once, not three times


def test_a_sheet_without_a_profile_entry_is_an_error():
    with pytest.raises(LayoutError, match="'Summary' has no entry"):
        layouts.read_rows(analytics_report(extra_sheet="Summary"), _analytics())


def test_a_new_year_sheet_with_the_same_header_is_read():
    """The entry is a pattern, not a list of eleven names: next year's sheet needs no edit."""
    rows = layouts.read_rows(analytics_report(extra_sheet="2025-26"), _analytics())
    assert len(rows) == 5 and not [r for r in rows if r.sheet == "2025-26"]  # header only, no error


def test_header_drift_fails_loudly():
    drifted = list(ANALYTICS_HEADER)
    drifted[15] = "Project State"
    with pytest.raises(LayoutError, match="column P reads 'project state'"):
        layouts.read_rows(analytics_report(header=drifted), _analytics())


def test_a_new_column_fails_loudly():
    with pytest.raises(LayoutError, match="column\\(s\\) U"):
        layouts.read_rows(analytics_report(header=[*ANALYTICS_HEADER, "CSR Unspent"]), _analytics())


def test_the_dataful_subset_reads():
    rows = layouts.read_rows(dataful_subset(), layouts.profile_for("mca_csr", DATAFUL_NAME))
    foundation = next(r for r in rows if r.text["company"] == "Kestrel Foundation")
    assert foundation.money["amount"].rupees == Decimal("0")      # a filed zero stays zero
    assert "state" not in foundation.text and foundation.mode == "not_stated"
    assert foundation.details == {"Group Company": "Kestrel", "Notes": "filed late"}
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_source_layouts.py -q`
Expected: failures. The first is `LayoutError: 0 layout profiles for mca_csr match`.

- [ ] **Step 4: Write the profiles**

Create `backend/app/ingest/data/source_layouts/mca_csr_analytics_report.json`:

```json
{
  "name": "mca_csr_analytics_report",
  "source_key": "mca_csr",
  "filename_pattern": "(?i)csr analytics report.*\\.xlsx$",
  "load": "read_only",
  "sheets": [
    {
      "sheet_pattern": "^\\d{4}-\\d{2}$",
      "layout": "table",
      "header_row": 1,
      "amount_unit": "crore",
      "kind": "line",
      "columns": [
        {"column": "A", "header": "Year", "field": "fiscal_year"},
        {"column": "B", "header": "Company Name", "field": "company"},
        {"column": "C", "header": "Class", "field": "detail"},
        {"column": "D", "header": "State", "field": "company_state"},
        {"column": "E", "header": "Company Type", "field": "detail"},
        {"column": "F", "header": "RoC", "field": "detail"},
        {"column": "G", "header": "Sub Category", "field": "detail"},
        {"column": "H", "header": "Listing Status", "field": "detail"},
        {"column": "I", "header": "Average Net Profit", "field": "avg_net_profit"},
        {"column": "J", "header": "CSR Prescribed Expenditure", "field": "prescribed_csr"},
        {"column": "K", "header": "CSR Spent", "field": "csr_spent"},
        {"column": "L", "header": "Local Area Spent", "field": "local_area_spent"},
        {"column": "M", "header": "S_No", "field": "omit"},
        {"column": "N", "header": "CSR_Project_s", "field": "project"},
        {"column": "O", "header": "Development_Sector_s", "field": "filed_sector"},
        {"column": "P", "header": "State", "field": "state"},
        {"column": "Q", "header": "District", "field": "district"},
        {"column": "R", "header": "Project_Amount_Outlay_INR_Cr", "field": "outlay"},
        {"column": "S", "header": "Amount_Spent_INR_Cr", "field": "amount"},
        {"column": "T", "header": "Mode_of_Implementation", "field": "implementation_mode"}
      ]
    }
  ]
}
```

Create `backend/app/ingest/data/source_layouts/mca_csr_dataful_subset.json`:

```json
{
  "name": "mca_csr_dataful_subset",
  "source_key": "mca_csr",
  "filename_pattern": "(?i)^dataful.*\\.xlsx$",
  "load": "read_only",
  "sheets": [
    {
      "sheet": "Sheet1",
      "layout": "table",
      "header_row": 1,
      "amount_unit": "crore",
      "kind": "line",
      "columns": [
        {"column": "A", "header": "Group Company", "field": "detail"},
        {"column": "B", "header": "Subsidiary / Entity (MCA Filer Name)", "field": "company"},
        {"column": "C", "header": "Fiscal Year", "field": "fiscal_year"},
        {"column": "D", "header": "State", "field": "state"},
        {"column": "E", "header": "District", "field": "district"},
        {"column": "F", "header": "Sector", "field": "filed_sector"},
        {"column": "G", "header": "CSR Project Name", "field": "project"},
        {"column": "H", "header": "Implementation Mode", "field": "implementation_mode"},
        {"column": "I", "header": "Project Amount Outlay (₹ Cr)", "field": "outlay"},
        {"column": "J", "header": "Amount Spent (₹ Cr)", "field": "amount"},
        {"column": "K", "header": "Notes", "field": "detail"}
      ]
    }
  ]
}
```

- [ ] **Step 5: Add the table reader**

Append to `backend/app/ingest/source_layouts.py`:

```python
def _read_table(ws: Any, name: str, spec: SheetProfile) -> Iterator[SourceRow]:
    rows = ws.iter_rows(min_row=spec.header_row, values_only=True)
    header = next(rows, None)
    if header is None:
        return  # an empty sheet: nothing to read, and nothing wrong
    _check_header(name, spec.header_row, tuple(header), spec.columns)
    index = [(rule, column_index_from_string(rule.column) - 1) for rule in spec.columns]
    first = min(i for _, i in index)
    for number, values in enumerate(rows, start=spec.header_row + 1):
        cells = [(rule, values[i] if i < len(values) else None) for rule, i in index]
        row = _row(name, f"{get_column_letter(first + 1)}{number}", spec, spec.kind, cells)
        if row is not None:
            yield row


_READERS["table"] = _read_table
```

Delete `backend/app/ingest/data/source_layouts/.gitkeep`.

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest tests/test_source_layouts.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add -A backend/app/ingest/source_layouts.py backend/app/ingest/data/source_layouts backend/tests/staff_source_fixtures.py backend/tests/test_source_layouts.py
git commit -m "feat(ingest): table layout and the two MCA filing profiles

Columns are named by letter and header, so the filer's State and the project's
State cannot swap; a drifted header or an unprofiled sheet stops the read.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The `blocks_by_column` layout and the CSO profile (profile and funder-details sheets)

**Files:**
- Modify: `backend/tests/staff_source_fixtures.py` (add `cso_workbook`)
- Create: `backend/app/ingest/data/source_layouts/cso_programmes_and_funders.json`
- Modify: `backend/app/ingest/source_layouts.py` (add `_read_blocks`)
- Test: `backend/tests/test_source_layouts.py`

**Interfaces:**

```python
def _read_blocks(ws, name: str, spec: SheetProfile) -> Iterator[SourceRow]   # _READERS["blocks_by_column"]
def cso_workbook(*, include: tuple[str, ...] = ("profile", "blocks", "sections"),
                 block_header: list[str] | None = None, unknown_heading: bool = False) -> bytes
CONTACT = "office@larkspur.example | +91 00000 00000"
```

Layout facts this task reproduces:

- **Blocks are found by the `Funder` cells in header row 2, not by merges.** One title merge (K1:M1) is narrower than its block (K..N).
- **Block widths vary:** 4 columns, or 5 with `Themetic`.
- **A block is re-titled and re-headed lower down,** and the repeat header leaves Project blank.
- **A merged sub-heading** ("Individual Donor") is context for the rows under it.
- **An un-merged single-cell row is data.**
- **Some blocks have nothing to read.** One is header-only, and one empty title merge has no header at all. Neither is an error.
- **Amounts are headed ₹ but carry per-cell units.**

- [ ] **Step 1: Write the fixture builder**

Append to `backend/tests/staff_source_fixtures.py`:

```python
CONTACT = "office@larkspur.example | +91 00000 00000"
PROFILE_HEADER = [
    "S.No", "Organisation Name", "State / District", "Year Est.", "Legal Status & Registration", "Vision",
    "Mission", "Objectives", "Thematic Areas", "Key Programmes & Initiatives", "Geographic Coverage",
    "Leadership", "Contact & Address",
]
SECTIONS_NOTE = (
    "Note: Grant amounts in ₹ Lakhs. Where a funder appears in multiple years, ONLY the largest amount "
    "is shown. Type: D = Domestic | F = Foreign | G = Government | CSR = Corporate Social Responsibility"
)


def _put(ws, row: int, start: str, values: list) -> None:
    from openpyxl.utils import column_index_from_string

    first = column_index_from_string(start)
    for offset, value in enumerate(values):
        if value is not None:
            ws.cell(row=row, column=first + offset, value=value)


def _profile_sheet(book: Workbook) -> None:
    ws = book.create_sheet("CSO Profile")
    ws["A1"] = "CSO ORGANISATION PROFILES"
    ws.merge_cells("A1:M1")
    _put(ws, 2, "A", PROFILE_HEADER)
    _put(ws, 3, "A", [1, "Larkspur Learning Trust", "Odisha / Northfield District", 2004,
                      "Public Charitable Trust, reg. TEST-0001", "Every child reads", "Village libraries",
                      "1. Libraries", "Education | Literacy", "Reading rooms", "Northfield District",
                      "Founder: A. Example", CONTACT])
    _put(ws, 4, "A", [2, "Riverbend Collective", "Assam / Eastvale", 2011, "Society", None, None, None,
                      "Livelihoods", "Farmer groups", "Eastvale", "Director: B. Example", CONTACT])


def _blocks_sheet(book: Workbook, block_header: list[str] | None) -> None:
    ws = book.create_sheet("CSO Funder Details")
    for ref, title, span in [("B1", "Larkspur Learning Trust", "B1:E1"), ("F1", "Riverbend Collective", "F1:J1"),
                             ("K1", "Moss Valley Society", "K1:M1"), ("O1", "Quiet Pines Trust", "O1:R1")]:
        ws[ref] = title
        ws.merge_cells(span)
    ws.merge_cells("S1:V1")                                   # an empty title over nothing
    _put(ws, 2, "B", block_header or ["Funder", "Project", "Year (2022-25)", "Grant (₹)"])
    _put(ws, 2, "F", ["Funder", "Project", "Themetic", "Year", "Grant (₹)"])
    _put(ws, 2, "K", ["Funder", "Project", "Year", "Fund Amount (Rs)"])
    _put(ws, 2, "O", ["Funder", "Project ", "Year", "Fund Size (₹)"])   # header only, no rows
    _put(ws, 3, "B", ["Alder Trust", "Reading Rooms", "2024-25", 450000])
    _put(ws, 4, "B", ["Birch CSR Foundation", "Teacher Training", "2024-25", "3,50,000"])
    ws["B5"] = "Individual Donor"
    ws.merge_cells("B5:E5")
    _put(ws, 6, "B", ["A. Donor", None, "Post 2022", "Not disclosed"])
    ws["B8"] = "Larkspur Learning Trust"                     # the block re-titled lower down
    ws.merge_cells("B8:E8")
    _put(ws, 9, "B", ["Funder", None, "Year", "Grant (₹)"])  # and re-headed, Project blank
    ws["B10"] = "Cedar Fund"                                  # one un-merged cell: data
    _put(ws, 11, "B", ["Kestrel Foundation", "stray note", "2021-22", 120000])
    _put(ws, 3, "F", ["Kestrel Foundation", "Solar Pumps", "Water", "2023-26", "12.5 Lakhs"])
    _put(ws, 3, "K", ["Dune Foundation", "Clinics", "2024-25", "1.2Cr"])
    _put(ws, 4, "K", ["Elm Trust", "Libraries", "2024-25", "4lakhs"])
    _put(ws, 5, "K", ["Fir Society", "Kits", "2024-25", "10,000 and materials"])


def _sections_sheet(book: Workbook, unknown_heading: bool) -> None:
    ws = book.create_sheet("CSO Current funder and Partners")
    ws["A1"] = "CSO FUNDER TRACKER"
    ws.merge_cells("A1:G1")
    ws["A2"] = SECTIONS_NOTE
    ws.merge_cells("A2:G2")
    funders_header = ["#", "Funder Name", "Type", "Category", "Year(s)", "Amount\n (₹ Lakhs)",
                      "Grant Purpose / Sector"]
    ws["A3"] = "1. Larkspur Learning Trust"
    ws.merge_cells("A3:G3")
    ws["A4"] = "FUNDERS"
    ws.merge_cells("A4:G4")
    _put(ws, 5, "A", funders_header)
    _put(ws, 6, "A", [1, "Alder Trust", "D", "Trust", "2021–2024", 25, "Libraries"])
    _put(ws, 7, "A", [2, "Kestrel Foundation", "CSR", "Corporate", "2023–2024", 7.5, "Water"])
    ws["A8"] = "PARTNERS & TECHNICAL SUPPORT ORGANISATIONS"
    ws.merge_cells("A8:C8")
    ws["A9"], ws["B9"], ws["D9"] = "#", "Partner / Technical Support Organisation", "Role & Nature of Support"
    ws.merge_cells("B9:C9")
    ws.merge_cells("D9:G9")
    ws["A10"], ws["B10"], ws["D10"] = 1, "Juniper Network", "Training"
    ws.merge_cells("B10:C10")
    ws.merge_cells("D10:G10")
    if unknown_heading:
        ws["A11"] = "VOLUNTEERS"
        ws.merge_cells("A11:G11")
        ws["A12"], ws["B12"] = 1, "Someone"
    ws["A13"] = "2. Riverbend Collective"
    ws.merge_cells("A13:G13")
    ws["A14"] = "FUNDERS"
    ws.merge_cells("A14:G14")
    _put(ws, 15, "A", funders_header)
    _put(ws, 16, "A", [1, "Gale Foundation", "F", "Foundation", "2023–2024", 12, "Farming"])


def cso_workbook(*, include: tuple[str, ...] = ("profile", "blocks", "sections"),
                 block_header: list[str] | None = None, unknown_heading: bool = False) -> bytes:
    book = Workbook()
    book.remove(book.active)
    if "profile" in include:
        _profile_sheet(book)
    if "blocks" in include:
        _blocks_sheet(book, block_header)
    if "sections" in include:
        _sections_sheet(book, unknown_heading)
    return _bytes(book)
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_source_layouts.py`:

```python
import json as _json

from tests.staff_source_fixtures import CONTACT, CSO_NAME, cso_workbook


def _cso():
    return layouts.profile_for("ffrh_funder_datasets", CSO_NAME)


def _blocks(**kw):
    rows = layouts.read_rows(cso_workbook(include=("profile", "blocks"), **kw), _cso())
    return {r.cell: r for r in rows if r.sheet == "CSO Funder Details"}


def test_the_profile_sheet_is_one_row_per_cso():
    rows = [r for r in layouts.read_rows(cso_workbook(include=("profile",)), _cso()) if r.sheet == "CSO Profile"]
    assert [(r.cell, r.text["cso"], r.kind) for r in rows] == [
        ("A3", "Larkspur Learning Trust", "profile"),
        ("A4", "Riverbend Collective", "profile"),
    ]
    assert rows[0].details["Legal Status & Registration"] == "Public Charitable Trust, reg. TEST-0001"
    assert rows[0].details["Leadership"] == "Founder: A. Example"


def test_contact_details_never_leave_the_parser():
    rows = layouts.read_rows(cso_workbook(), _cso())
    dumped = _json.dumps([r.to_json() for r in rows], ensure_ascii=False)
    assert "larkspur.example" not in dumped and "+91" not in dumped


def test_blocks_are_found_by_their_header_not_their_merge():
    found = _blocks()
    assert {c for c in found} == {"B3", "B4", "B6", "B10", "B11", "F3", "K3", "K4", "K5"}
    assert found["K3"].text["cso"] == "Moss Valley Society"      # title merge K1:M1, block K..N
    assert found["K3"].money["amount"].rupees == Decimal("12000000")
    assert all(r.kind == "funder" for r in found.values())


def test_a_five_column_block_keeps_its_purpose():
    row = _blocks()["F3"]
    assert (row.text["cso"], row.text["funder"], row.text["purpose"]) == (
        "Riverbend Collective", "Kestrel Foundation", "Water")
    assert (row.fiscal_year, row.period) == (None, "2023-26")


def test_a_cell_suffix_overrides_the_sheet_unit():
    found = _blocks()
    assert found["F3"].money["amount"].rupees == Decimal("1250000") and found["F3"].money["amount"].unit == "lakh"
    assert found["K4"].money["amount"].rupees == Decimal("400000")
    assert found["B3"].money["amount"].rupees == Decimal("450000") and found["B3"].money["amount"].unit == "inr"
    assert found["B4"].money["amount"].rupees == Decimal("350000")
    assert found["K5"].money["amount"].rupees is None
    assert found["K5"].money["amount"].raw == "10,000 and materials"


def test_a_merged_sub_heading_is_context_and_a_single_cell_is_data():
    found = _blocks()
    assert found["B6"].context == {"heading": "Individual Donor"}
    assert found["B6"].money["amount"].rupees is None and found["B6"].period == "Post 2022"
    assert found["B10"].text == {"funder": "Cedar Fund", "cso": "Larkspur Learning Trust"}
    assert found["B10"].context == {}                 # the re-title cleared the sub-heading


def test_a_value_under_a_blank_repeat_header_is_kept_not_dropped():
    row = _blocks()["B11"]
    assert row.details == {"unlabelled column C": "stray note"}
    assert row.fiscal_year == "FY2021-22"


def test_an_unknown_block_header_is_an_error():
    with pytest.raises(LayoutError, match="header 'donor' is not in the profile"):
        _blocks(block_header=["Funder", "Donor", "Year", "Grant (₹)"])


def test_header_only_and_empty_blocks_are_not_errors():
    assert not [c for c in _blocks() if c.startswith(("O", "S"))]
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_source_layouts.py -q -k "cso or block or contact or profile_sheet or suffix or merged or unlabelled or blank"`
Expected: `LayoutError: 0 layout profiles for ffrh_funder_datasets match`.

- [ ] **Step 4: Write the profile (two sheets)**

Create `backend/app/ingest/data/source_layouts/cso_programmes_and_funders.json`:

```json
{
  "name": "cso_programmes_and_funders",
  "source_key": "ffrh_funder_datasets",
  "filename_pattern": "(?i)details of programs and current funders.*\\.xlsx$",
  "load": "full",
  "sheets": [
    {
      "sheet": "CSO Profile",
      "layout": "table",
      "header_row": 2,
      "amount_unit": "inr",
      "kind": "profile",
      "columns": [
        {"column": "A", "header": "S.No", "field": "omit"},
        {"column": "B", "header": "Organisation Name", "field": "cso"},
        {"column": "C", "header": "State / District", "field": "detail"},
        {"column": "D", "header": "Year Est.", "field": "detail"},
        {"column": "E", "header": "Legal Status & Registration", "field": "detail"},
        {"column": "F", "header": "Vision", "field": "detail"},
        {"column": "G", "header": "Mission", "field": "detail"},
        {"column": "H", "header": "Objectives", "field": "detail"},
        {"column": "I", "header": "Thematic Areas", "field": "detail"},
        {"column": "J", "header": "Key Programmes & Initiatives", "field": "detail"},
        {"column": "K", "header": "Geographic Coverage", "field": "detail"},
        {"column": "L", "header": "Leadership", "field": "detail"},
        {"column": "M", "header": "Contact & Address", "field": "omit"}
      ]
    },
    {
      "sheet": "CSO Funder Details",
      "layout": "blocks_by_column",
      "title_row": 1,
      "header_row": 2,
      "block_start_header": ["Funder"],
      "title_field": "cso",
      "amount_unit": "inr",
      "kind": "funder",
      "columns": [
        {"header": "Funder", "field": "funder"},
        {"header": "Project", "field": "project"},
        {"header": ["Themetic", "Thematic"], "field": "purpose"},
        {"header": ["Year", "Year (2022-25)", "Year(s)"], "field": "fiscal_year"},
        {"header": ["Grant (₹)", "Fund Amount (Rs)", "Fund Size (₹)"], "field": "amount"}
      ]
    }
  ]
}
```

`Contact & Address` is declared `omit`. Personal emails and phone numbers never leave the parser, so they never reach the model, the sidecar or a trace.

- [ ] **Step 5: Add the blocks reader**

Append to `backend/app/ingest/source_layouts.py`:

```python
def _merged_spans(ws: Any) -> dict[tuple[int, int], int]:
    """(row, col) of each merged range's top-left cell -> how many columns it spans."""
    return {(r.min_row, r.min_col): r.max_col - r.min_col + 1 for r in ws.merged_cells.ranges}


def _merged_value(ws: Any, row: int, col: int) -> Any:
    value = ws.cell(row=row, column=col).value
    if value is not None:
        return value
    for r in ws.merged_cells.ranges:
        if r.min_row <= row <= r.max_row and r.min_col <= col <= r.max_col:
            return ws.cell(row=r.min_row, column=r.min_col).value
    return None


def _block_columns(sheet: str, ws: Any, row: int, start: int, end: int,
                   by_header: dict[str, ColumnRule]) -> dict[int, ColumnRule]:
    columns: dict[int, ColumnRule] = {}
    for col in range(start, end + 1):
        text = _norm(ws.cell(row=row, column=col).value)
        if not text:
            continue
        rule = by_header.get(text)
        if rule is None:
            raise LayoutError(
                f"sheet {sheet!r} {get_column_letter(col)}{row}: header {text!r} is not in the profile's columns"
            )
        columns[col] = rule
    return columns


def _read_blocks(ws: Any, name: str, spec: SheetProfile) -> Iterator[SourceRow]:
    """Side-by-side blocks. A block starts at each header-row cell that reads a start header
    (e.g. "Funder") and runs to the column before the next one. That is the header's own
    width: a title merge can be narrower than the block beneath it.

    Within a block, top to bottom:
      - a row whose first cell reads a start header re-heads the block (columns re-read; a
        blank header unmaps its column, and a value found under it is kept as unlabelled);
      - a row with only its first cell filled, and that cell merged across the block, is a
        heading: the block's own title again, or a sub-heading carried as context;
      - anything else with a value is a record.
    """
    starts_text = set(spec.block_start_header)
    width = ws.max_column
    header = [ws.cell(row=spec.header_row, column=c).value for c in range(1, width + 1)]
    starts = [c for c in range(1, width + 1) if _norm(header[c - 1]) in starts_text]
    if not starts:
        raise LayoutError(f"sheet {name!r} row {spec.header_row}: no block header found")
    last = max(c for c in range(1, width + 1) if _norm(header[c - 1]))
    spans = _merged_spans(ws)
    by_header = {h: rule for rule in spec.columns for h in rule.header}
    for i, start in enumerate(starts):
        end = starts[i + 1] - 1 if i + 1 < len(starts) else last
        title = _text(_merged_value(ws, spec.title_row, start)) if spec.title_row else None
        columns = _block_columns(name, ws, spec.header_row, start, end, by_header)
        context: dict[str, str] = {}
        for r in range(spec.header_row + 1, ws.max_row + 1):
            values = {c: ws.cell(row=r, column=c).value for c in range(start, end + 1)}
            filled = [c for c, v in values.items() if _text(v) is not None]
            if not filled:
                continue
            if _norm(values[start]) in starts_text:
                columns = _block_columns(name, ws, r, start, end, by_header)
                continue
            if filled == [start] and spans.get((r, start), 1) > 1:
                heading = _text(values[start])
                if _norm(heading) == _norm(title):
                    context.pop("heading", None)
                else:
                    context["heading"] = heading or ""
                continue
            row = _row(name, f"{get_column_letter(start)}{r}", spec, spec.kind,
                       [(rule, values[c]) for c, rule in columns.items()],
                       context=context, fixed={spec.title_field: title} if spec.title_field else None)
            if row is None:
                continue
            for c, v in values.items():
                if c not in columns and _text(v) is not None:
                    row.details[f"unlabelled column {get_column_letter(c)}"] = _text(v) or ""
            yield row


_READERS["blocks_by_column"] = _read_blocks
```

The "Cedar Fund" row at B10 has only one cell filled, so `_row` returns a record and `seen` is true. The B11 row's value under the blank re-header is mapped to no rule, so `_row` never sees it. The loop above keeps it as `unlabelled column C`.

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest tests/test_source_layouts.py -q`
Expected: all pass. A workbook that includes `sections` is not read until Task 5, because that sheet has no profile entry yet. No test here includes it except `test_contact_details_never_leave_the_parser`. Mark that test `@pytest.mark.xfail(raises=LayoutError, strict=True, reason="sections entry lands in Task 5")` now, and remove the mark in Task 5.

- [ ] **Step 7: Commit**

```bash
git add backend/app/ingest/source_layouts.py backend/app/ingest/data/source_layouts/cso_programmes_and_funders.json backend/tests/staff_source_fixtures.py backend/tests/test_source_layouts.py
git commit -m "feat(ingest): side-by-side blocks layout and the CSO profile sheet

Blocks are found by their header cells, re-headed blocks re-read their columns,
contact details are declared and dropped at parse time.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The `sections_by_heading` layout and the third CSO sheet

**Files:**
- Modify: `backend/app/ingest/data/source_layouts/cso_programmes_and_funders.json` (add the third entry)
- Modify: `backend/app/ingest/source_layouts.py` (add `_read_sections`)
- Test: `backend/tests/test_source_layouts.py`

**Interfaces:** `def _read_sections(ws, name: str, spec: SheetProfile) -> Iterator[SourceRow]`, registered as `_READERS["sections_by_heading"]`.

Layout facts this task reproduces:

- **Each section opens with a numbered heading,** `1. <CSO>`.
- **Each section has two headed sub-tables,** `FUNDERS` and `PARTNERS & TECHNICAL SUPPORT ORGANISATIONS`, and each has its own header row.
- **The partners table uses merged B:C and D:G.**
- **The A2 note matters.** It says amounts are in lakh and are the *largest across years*, not a per-year figure. It also decodes Type D/F/G/CSR. The note travels on every row.
- **Years are ranges with en dashes.** They are periods, not fiscal years.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_source_layouts.py`:

```python
def _sections(**kw):
    rows = layouts.read_rows(cso_workbook(**kw), _cso())
    return {r.cell: r for r in rows if r.sheet == "CSO Current funder and Partners"}


def test_sections_read_both_sub_tables():
    found = _sections()
    assert {c: (r.kind, r.text["cso"]) for c, r in found.items()} == {
        "A6": ("funder", "Larkspur Learning Trust"),
        "A7": ("funder", "Larkspur Learning Trust"),
        "A10": ("partner", "Larkspur Learning Trust"),
        "A16": ("funder", "Riverbend Collective"),
    }
    assert found["A10"].text["partner"] == "Juniper Network" and found["A10"].text["role"] == "Training"


def test_amounts_are_lakh():
    found = _sections()
    assert found["A6"].money["amount"].rupees == Decimal("2500000")
    assert found["A7"].money["amount"].rupees == Decimal("750000")
    assert found["A16"].money["amount"].unit == "lakh"


def test_the_sheet_note_and_type_codes_travel_with_every_row():
    row = _sections()["A7"]
    assert "ONLY the largest amount" in row.context["note"]
    assert row.text["funder_type"] == "corporate CSR (CSR)"
    assert _sections()["A16"].text["funder_type"] == "foreign (F)"
    assert (row.fiscal_year, row.period) == (None, "2023–2024")


def test_an_unknown_section_heading_is_an_error():
    with pytest.raises(LayoutError, match="A11: a heading the profile does not know"):
        _sections(unknown_heading=True)


def test_every_sheet_of_the_cso_workbook_is_read():
    rows = layouts.read_rows(cso_workbook(), _cso())
    assert {r.sheet for r in rows} == {"CSO Profile", "CSO Funder Details", "CSO Current funder and Partners"}
```

Remove the `xfail` mark from `test_contact_details_never_leave_the_parser`.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_source_layouts.py -q`
Expected: failures with `LayoutError: sheet 'CSO Current funder and Partners' has no entry`.

- [ ] **Step 3: Add the profile entry**

Append this object to `"sheets"` in `cso_programmes_and_funders.json`:

```json
    {
      "sheet": "CSO Current funder and Partners",
      "layout": "sections_by_heading",
      "section_pattern": "^\\s*\\d+\\.\\s+(?P<title>\\S.*?)\\s*$",
      "title_field": "cso",
      "note_cell": "A2",
      "amount_unit": "lakh",
      "kind": "funder",
      "codes": {"funder_type": {"D": "domestic", "F": "foreign", "G": "government", "CSR": "corporate CSR"}},
      "tables": [
        {
          "heading": ["FUNDERS"],
          "kind": "funder",
          "columns": [
            {"column": "A", "header": "#", "field": "omit"},
            {"column": "B", "header": "Funder Name", "field": "funder"},
            {"column": "C", "header": "Type", "field": "funder_type"},
            {"column": "D", "header": "Category", "field": "detail"},
            {"column": "E", "header": "Year(s)", "field": "fiscal_year"},
            {"column": "F", "header": "Amount (₹ Lakhs)", "field": "amount"},
            {"column": "G", "header": "Grant Purpose / Sector", "field": "purpose"}
          ]
        },
        {
          "heading": ["PARTNERS & TECHNICAL SUPPORT ORGANISATIONS"],
          "kind": "partner",
          "columns": [
            {"column": "A", "header": "#", "field": "omit"},
            {"column": "B", "header": "Partner / Technical Support Organisation", "field": "partner"},
            {"column": "D", "header": "Role & Nature of Support", "field": "role"}
          ]
        }
      ]
    }
```

- [ ] **Step 4: Add the sections reader**

Append to `backend/app/ingest/source_layouts.py`:

```python
def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) or bool(re.fullmatch(r"\d+\.?", str(value or "").strip()))


def _read_sections(ws: Any, name: str, spec: SheetProfile) -> Iterator[SourceRow]:
    """Numbered sections, each with headed sub-tables.

    Rows before the first section (a title, a note) are skipped. Inside a section, a row with
    only column A filled and not a number is a heading: a known sub-table heading switches
    the table, and anything else is an error, because the rows under it would be lost.
    """
    pattern = re.compile(spec.section_pattern or "")
    note = _text(ws[spec.note_cell].value) if spec.note_cell else None
    context = {"note": note} if note else {}
    headings = {h: t for t in spec.tables for h in t.heading}
    section: str | None = None
    table: TableSpec | None = None
    header_seen = False
    for r in range(1, ws.max_row + 1):
        values = tuple(ws.cell(row=r, column=c).value for c in range(1, ws.max_column + 1))
        filled = [i for i, v in enumerate(values) if _text(v) is not None]
        if not filled:
            continue
        only_first = filled == [0]
        first = _text(values[0]) if values else None
        title = pattern.match(first) if (first and only_first) else None
        if title:
            section, table, header_seen = title["title"], None, False
            continue
        if section is None:
            continue
        if only_first and _norm(first) in headings:
            table, header_seen = headings[_norm(first)], False
            continue
        if table is not None and not header_seen:
            _check_header(name, r, values, table.columns)
            header_seen = True
            continue
        if only_first and not _is_number(values[0]):
            raise LayoutError(
                f"sheet {name!r} A{r}: a heading the profile does not know - add it to 'tables', or the "
                f"rows under it would be lost"
            )
        if table is None:
            raise LayoutError(f"sheet {name!r} row {r}: a row before any table heading in its section")
        cells = []
        for rule in table.columns:
            i = column_index_from_string(rule.column) - 1
            cells.append((rule, values[i] if i < len(values) else None))
        row = _row(name, f"A{r}", spec, table.kind, cells, context=context,
                   fixed={spec.title_field: section} if spec.title_field else None)
        if row is not None:
            yield row


_READERS["sections_by_heading"] = _read_sections
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && pytest tests/test_source_layouts.py -q`
Expected: all pass.

- [ ] **Step 6: Run the profiles against the real files (local only, nothing committed)**

This is the only place the real files are touched. Run it on the developer's machine. It prints counts and sheet names only, never values.

```bash
cd backend && DATAFUL="$HOME/Downloads/<the subset file>" CSO="$HOME/Downloads/<the CSO workbook>" .venv/bin/python - <<'EOF'
from pathlib import Path
from collections import Counter
from app.ingest import source_layouts as L
import os
for path, key in [(Path(os.environ["DATAFUL"]), "mca_csr"), (Path(os.environ["CSO"]), "ffrh_funder_datasets")]:
    p = L.profile_for(key, path.name)
    rows = L.read_rows(path.read_bytes(), p)
    print(p.name, Counter(r.sheet for r in rows), sum(1 for r in rows for m in r.money.values() if m.rupees is None and m.raw))
EOF
```

Expected: every sheet is listed with a non-zero count (the header-only block contributes none), and no `LayoutError`. If a `LayoutError` appears, fix the **profile**, not the parser, unless the error is a parser bug. Then add a synthetic fixture reproducing the shape that caused it.

Do not run the 59 MB analytics report here. Task 8 runs it with `--split-sheets`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/ingest/source_layouts.py backend/app/ingest/data/source_layouts/cso_programmes_and_funders.json backend/tests/test_source_layouts.py
git commit -m "feat(ingest): headed-sections layout; the CSO workbook reads in full

Amounts in lakh, the sheet note and type codes carried on every row, an unknown
heading inside a section fails rather than losing the rows under it.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The `staff-sources` bucket

**Files:**
- Create: `db/migrations/0032_staff_sources_bucket.sql` (renumber at merge so it lands after (b))
- Modify: `backend/app/integrations/storage.py`
- Modify: `backend/app/api/routes/documents.py`
- Test: `backend/tests/test_storage.py`, `backend/tests/test_vault.py`

**Interfaces:**

```python
STAFF_SOURCES = "staff-sources"
BUCKETS: tuple[str, ...] = (SOURCE_ARCHIVE, ORG_VAULT, STAFF_SOURCES)
def split(storage_path: str) -> tuple[str, str] | None   # now also staff-sources
```

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_storage.py`:

```python
STAFF_MIGRATION = next(
    iter(sorted((MIGRATION.parent).glob("*_staff_sources_bucket.sql"))), MIGRATION.parent / "missing.sql"
)


class TestStaffSourcesBucket:
    def sql(self) -> str:
        if not STAFF_MIGRATION.exists():
            pytest.fail("no *_staff_sources_bucket.sql migration")
        return STAFF_MIGRATION.read_text(encoding="utf-8")

    def test_creates_a_private_bucket(self):
        rows = re.findall(r"\('staff-sources',\s*'staff-sources',\s*(\w+)", self.sql())
        assert rows == ["false"]

    def test_is_guarded_and_idempotent(self):
        sql = self.sql()
        assert -1 < sql.find("pg_namespace") < sql.find("INSERT INTO storage.buckets")
        assert "ON CONFLICT" in sql

    def test_the_bucket_policy_is_staff_and_select_only(self):
        sql = self.sql()
        policies = re.findall(r"CREATE POLICY \w+ ON storage\.objects FOR (\w+)", sql)
        assert policies == ["SELECT"]
        assert "bucket_id = 'staff-sources' AND (SELECT app.is_staff())" in sql
        assert "to_regprocedure('app.is_staff()')" in sql
        assert "insufficient_privilege" in sql   # fail closed, never break the migration

    def test_split_knows_the_bucket(self):
        assert storage.split("staff-sources/0123456789ab-x.xlsx") == ("staff-sources", "0123456789ab-x.xlsx")
        assert storage.split("elsewhere/x") is None
```

Append to `backend/tests/test_vault.py`, inside `class TestDownloading`:

```python
    async def test_a_staff_object_on_a_public_row_is_never_signed(self, client_for, monkeypatch, storage_on):
        """Only the upload script writes staff-sources paths, always on a private row with no org.
        A row claiming one while public, or an org's, is not one it wrote."""
        for row in ({"is_public": True, "org_id": None}, {"is_public": False, "org_id": 3}):
            async def fake_row(pool, *, document_id, user_id, row=row):
                return {"id": 7, "title": "x", "storage_path": "staff-sources/0123456789ab-x.xlsx", **row}

            monkeypatch.setattr(f"{ROUTE}.repo.readable_document", fake_row)
            monkeypatch.setattr(f"{ROUTE}.storage.signed_url", lambda b, k: _async("https://p/signed"))
            async with client_for(documents_api.router) as client:
                response = await client.get("/api/documents/7/file")
            assert response.status_code == 404

    async def test_staff_may_download_a_staff_dataset(self, client_for, monkeypatch, storage_on):
        async def fake_row(pool, *, document_id, user_id):
            return {"id": 7, "title": "x", "storage_path": "staff-sources/0123456789ab-x.xlsx",
                    "is_public": False, "org_id": None}

        monkeypatch.setattr(f"{ROUTE}.repo.readable_document", fake_row)
        monkeypatch.setattr(f"{ROUTE}.storage.signed_url", lambda b, k: _async(f"https://p/{b}/{k}?t=1"))
        async with client_for(documents_api.router) as client:
            response = await client.get("/api/documents/7/file")
        assert response.status_code == 200
        assert "/staff-sources/" in response.json()["url"]
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_storage.py tests/test_vault.py -q -k "staff"`
Expected: `no *_staff_sources_bucket.sql migration`, and `split` returns None.

- [ ] **Step 3: Write the migration**

Create `db/migrations/0032_staff_sources_bucket.sql`:

```sql
-- A third private bucket, staff-sources: datasets a staff member uploads by hand - statutory
-- CSR filings exported from an Indian network or a licensed mirror, and the CSO funder workbook
-- shared under partner permission. Spec D8: readable by staff (users.is_staff) only, never by an
-- org admin.
--
--   staff-sources   <sha256(bytes)[:12]>-<profile>[--<sheet>].xlsx      the workbook, as uploaded
--                   <that key>.<profile digest>.rows.jsonl.gz            its rows, normalised once
--
-- A bucket separates access rules (0020). This is a third rule: source-archive is anyone signed
-- in, org-vault is an org's own people, staff-sources is staff alone.
--
-- Each object has a documents row: doc_type 'source_dataset', is_public false, no org, no
-- funder, no content_md, no chunks. documents_read (0027) already limits such a row to staff,
-- and readable_document() does the same for the download route. The contents never enter the
-- database, so the SQL tool, which runs as the owner, cannot read them.
--
-- Guarded like 0020: the local container has no storage schema, and applied there this is a
-- no-op that still records in schema_migrations, so the ledgers match.
--
-- Number: after the funder-model migration (PR b), which follows #98's 0030. Reassigned at merge
-- if the open branches land in another order.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'storage') THEN
    RAISE NOTICE 'no storage schema (not Supabase) - skipping the staff-sources bucket';
    RETURN;
  END IF;

  -- 50 MB, the same ceiling as 0020 and MAX_ARCHIVE_BYTES. A workbook over it is stored one sheet
  -- per object (scripts/upload_staff_source.py --split-sheets), not by raising this.
  INSERT INTO storage.buckets (id, name, public, file_size_limit)
  VALUES ('staff-sources', 'staff-sources', false, 52428800)
  ON CONFLICT (id) DO NOTHING;

  -- The app never reads Storage as the caller: it signs URLs with the service key. With no
  -- policy at all, only the service role reads this bucket. This policy is for a staff client
  -- reading directly, and it is staff alone, SELECT only. Nothing writes here but the upload
  -- script, with the service key.
  IF to_regprocedure('app.is_staff()') IS NULL THEN
    RAISE NOTICE 'app.is_staff() missing - staff-sources gets no read policy; only the service role reads it';
    RETURN;
  END IF;
  BEGIN
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'storage' AND tablename = 'objects' AND policyname = 'staff_sources_staff_read'
    ) THEN
      CREATE POLICY staff_sources_staff_read ON storage.objects FOR SELECT TO authenticated
        USING (bucket_id = 'staff-sources' AND (SELECT app.is_staff()));
    END IF;
  EXCEPTION WHEN insufficient_privilege THEN
    -- Fail closed: without the policy only the service role reads the bucket.
    RAISE NOTICE 'not permitted to add a policy on storage.objects - staff-sources stays service-role only';
  END;
END
$$;
```

- [ ] **Step 4: Teach `storage.py` the bucket**

In `backend/app/integrations/storage.py`, after `ORG_VAULT = "org-vault"`, add:

```python
# Staff-only datasets uploaded by hand (scripts/upload_staff_source.py). 0032 creates it.
STAFF_SOURCES = "staff-sources"
BUCKETS: tuple[str, ...] = (SOURCE_ARCHIVE, ORG_VAULT, STAFF_SOURCES)
```

Then replace the body and docstring of `split`:

```python
def split(storage_path: str) -> tuple[str, str] | None:
    """`documents.storage_path` back into (bucket, key). None if it is not one of ours - a path
    we did not write is not one we will hand out a URL for.
    """
    bucket, _, key = storage_path.partition("/")
    return (bucket, key) if key and bucket in BUCKETS else None
```

- [ ] **Step 5: Guard the download route**

In `backend/app/api/routes/documents.py`, in `document_file`, after `parts = storage.split(row["storage_path"])` and its `None` check, insert:

```python
    # A staff dataset is staff-only by its row: private, and no org's. Only the upload script
    # writes staff-sources paths, and always on such a row; one that claims a staff-sources
    # object while public or an org's was not written by it, so it is never signed.
    if parts[0] == storage.STAFF_SOURCES and (row["is_public"] or row["org_id"] is not None):
        raise HTTPException(404, f"document {document_id} has no readable file")
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest tests/test_storage.py tests/test_vault.py -q -m "not integration"`
Expected: all pass.

Run: `make migrate && make migrate-status`
Expected: `0032_staff_sources_bucket.sql` applied, with the NOTICE `no storage schema (not Supabase) - skipping the staff-sources bucket`.

- [ ] **Step 7: Commit**

```bash
git add db/migrations/0032_staff_sources_bucket.sql backend/app/integrations/storage.py backend/app/api/routes/documents.py backend/tests/test_storage.py backend/tests/test_vault.py
git commit -m "feat(storage): private staff-sources bucket, readable by staff alone

Guarded like 0020; the read policy is SELECT for app.is_staff() and fails closed
where the role may not add one. The download route never signs a staff object
on a public or org row.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Dataset rows, alias lookup and the read path

**Files:**
- Modify: `backend/app/repositories/documents.py`, `backend/app/repositories/funders.py`
- Create: `backend/app/ingest/staff_sources.py`
- Test: `backend/tests/test_staff_sources.py` (create), `backend/tests/test_rls.py`, `backend/tests/test_vault.py`

**Interfaces:**

```python
# repositories/documents.py
async def insert_source_dataset(pool, *, title: str, source_key: str, storage_path: str, source_url: str,
                                content_hash: str, extractor_version: str, as_of: str | None) -> int
async def source_dataset_by_hash(pool, *, content_hash: str) -> dict | None
async def list_source_datasets(pool, *, source_keys: list[str] | None = None) -> list[dict]
# repositories/funders.py
async def name_variants(pool, *, match: str, limit: int = 5) -> list[dict]   # slug, name, aliases
# app/ingest/staff_sources.py
DOC_TYPE = "source_dataset"
SOURCE_URL_PREFIX = "https://staff-sources.sangam.invalid/"
def object_key(data: bytes, stored_name: str) -> str
def source_url(data: bytes) -> str
def is_staff_source_url(url: str | None) -> bool
def sidecar_key(key: str, profile: LayoutProfile) -> str
def encode_rows(rows: Iterable[SourceRow]) -> bytes
def decode_rows(blob: bytes, terms: list[str]) -> Iterator[SourceRow]
async def search(pool, match: str, *, source_keys: list[str] | None = None,
                 fiscal_years: list[str] | None = None, limit: int = 500) -> str
```

**Why a `.invalid` URL.** `FindingBase.source_url` accepts only an http(s) URL. A staff dataset has no public address, and must not be given one that resolves. Each dataset therefore gets `https://staff-sources.sangam.invalid/<sha12>`:

- `.invalid` is reserved by RFC 2606, so it never resolves and is never mistaken for a page;
- it carries no file name, so when it lands in a public `funder_activity.source_url` it reveals nothing;
- Task 10 maps it back to the private `documents` row.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_staff_sources.py`:

```python
"""The staff-dataset read path: rows, sidecars, the search and what it renders.

Unit tests monkeypatch the repositories and Storage; nothing here touches a database
except the classes marked integration.
"""

from __future__ import annotations

import logging

import pytest

from app.ingest import source_layouts as layouts
from app.ingest import staff_sources
from tests.staff_source_fixtures import ANALYTICS_NAME, CSO_NAME, analytics_report, cso_workbook

MCA = layouts.profile_for("mca_csr", ANALYTICS_NAME)
CSO = layouts.profile_for("ffrh_funder_datasets", CSO_NAME)


def _dataset(doc_id: int, data: bytes, profile, key_name: str | None = None) -> dict:
    key = staff_sources.object_key(data, key_name or profile.stored_name)
    return {"id": doc_id, "title": f"Staff dataset · {profile.source_key} · {profile.name}",
            "source_name": profile.source_key, "source_url": staff_sources.source_url(data),
            "storage_path": f"staff-sources/{key}", "content_hash": "h", "extractor_version": profile.version,
            "as_of": None}


@pytest.fixture
def world(monkeypatch):
    """Two datasets in Storage, each with a current sidecar; one funder with one alias."""
    staff_sources._cache.clear()
    objects: dict[str, bytes] = {}
    docs = []
    for doc_id, data, profile in [(41, analytics_report(), MCA), (42, cso_workbook(), CSO)]:
        doc = _dataset(doc_id, data, profile)
        key = doc["storage_path"].partition("/")[2]
        objects[key] = data
        objects[staff_sources.sidecar_key(key, profile)] = staff_sources.encode_rows(layouts.iter_rows(data, profile))
        docs.append(doc)

    async def download(bucket, key, max_bytes=None):
        assert bucket == "staff-sources"
        return objects.get(key)

    async def datasets(pool, *, source_keys=None):
        return [d for d in docs if not source_keys or d["source_name"] in source_keys]

    async def variants(pool, *, match, limit=5):
        if "kestrel" in match.lower():
            return [{"slug": "kestrel-foundation", "name": "Kestrel Foundation",
                     "aliases": ["Kestrel Polymers Limited"]}]
        return []

    monkeypatch.setattr(staff_sources.storage, "download", download)
    monkeypatch.setattr(staff_sources.documents_repo, "list_source_datasets", datasets)
    monkeypatch.setattr(staff_sources.funders_repo, "name_variants", variants)
    return objects


async def test_every_dataset_and_sheet_is_searched(world):
    out = await staff_sources.search(object(), "Kestrel Foundation")
    assert "[source:41#2023-24:A2]" in out                        # MCA, via the alias
    assert "[source:42#CSO Funder Details:F3]" in out             # a block
    assert "[source:42#CSO Current funder and Partners:A7]" in out  # a section


async def test_amounts_are_rupees_with_the_printed_figure_beside(world):
    out = await staff_sources.search(object(), "Kestrel Polymers")
    assert "amount ₹1,200,000 (as printed: '0.12' crore)" in out
    assert "outlay not stated (as printed: 'Nec/ Not Mentioned')" in out


async def test_company_figures_appear_once_per_company_year(world):
    out = await staff_sources.search(object(), "Kestrel Polymers", fiscal_years=["FY2023-24"])
    assert out.count("company-year 'Kestrel Polymers Limited'") == 1
    assert "CSR spent ₹3,000,000 (as printed: '0.3' crore)" in out


async def test_every_sheet_is_headed_and_none_is_withheld(world):
    """D14: the CSO funder sheets are cited and saved like the filings; no sheet carries a warning."""
    out = await staff_sources.search(object(), "Kestrel Foundation", source_keys=["ffrh_funder_datasets"])
    assert "### sheet 'CSO Funder Details'" in out
    assert "### sheet 'CSO Current funder and Partners'" in out
    assert "do not save" not in out
    assert "### sheet 'CSO Profile'" not in out  # Kestrel is not a CSO


async def test_each_dataset_prints_what_a_finding_cites(world):
    out = await staff_sources.search(object(), "Kestrel Polymers")
    assert "source_url for a finding: https://staff-sources.sangam.invalid/" in out
    assert "source_name: mca_csr" in out


async def test_a_year_filter_counts_what_it_left_out(world):
    out = await staff_sources.search(object(), "Kestrel Foundation", fiscal_years=["FY2023-24"])
    assert "give a period rather than one fiscal year" in out
    assert "F3]" not in out


async def test_the_limit_is_reported(world):
    out = await staff_sources.search(object(), "Kestrel", limit=1)
    assert "more rows not shown" in out


async def test_no_match_says_where_to_look_next(world):
    out = await staff_sources.search(object(), "Nobody Anywhere")
    assert "No row" in out and "parent company" in out


async def test_a_stale_sidecar_falls_back_to_the_workbook(world):
    for key in [k for k in world if k.endswith(staff_sources.SIDECAR_SUFFIX)]:
        del world[key]
    out = await staff_sources.search(object(), "Kestrel Polymers")
    assert "[source:41#2023-24:A2]" in out and "parsed from the workbook" in out


async def test_one_unreadable_dataset_does_not_hide_the_others(world, monkeypatch):
    async def datasets(pool, *, source_keys=None):
        bad = _dataset(43, b"not a workbook", MCA, key_name="broken.xlsx")
        bad["extractor_version"] = "source_layouts/no_such_profile@00000000"
        return [*await _orig(pool), bad]

    _orig = staff_sources.documents_repo.list_source_datasets
    monkeypatch.setattr(staff_sources.documents_repo, "list_source_datasets", datasets)
    out = await staff_sources.search(object(), "Kestrel Polymers")
    assert "[source:41#2023-24:A2]" in out
    assert "document 43 (mca_csr) could not be read" in out


@pytest.mark.parametrize("bad, said", [("Ke", "at least three letters"), ("", "at least three letters")])
async def test_a_short_name_is_refused(world, bad, said):
    assert said in await staff_sources.search(object(), bad)


async def test_a_malformed_year_is_refused(world):
    assert "FY2023-24" in await staff_sources.search(object(), "Kestrel", fiscal_years=["2023"])


async def test_nothing_from_a_row_reaches_the_log(world, caplog):
    caplog.set_level(logging.DEBUG)
    await staff_sources.search(object(), "Kestrel Foundation")
    for secret in ("Kestrel", "Larkspur", "Rural Schools", "1200000", "0.12"):
        assert secret not in caplog.text


def test_contact_details_are_not_in_the_sidecar():
    blob = staff_sources.encode_rows(layouts.iter_rows(cso_workbook(), CSO))
    rows = list(staff_sources.decode_rows(blob, ["larkspur learning trust"]))
    assert rows and all("larkspur.example" not in str(r.to_json()) for r in rows)
```

Append to `backend/tests/test_rls.py`:

```python
@pytest.mark.parametrize(
    "name, expected",
    [("anon", 0), ("nobody", 0), ("member_a", 0), ("steward_a", 0), ("admin_a", 0), ("staff", 1)],
)
def test_a_staff_dataset_reaches_only_staff(db, name, expected):
    """Spec D8: an org admin is not staff."""
    conn, world = db
    doc = conn.execute(
        "INSERT INTO documents (title, doc_type, source_name, is_public, storage_path) "
        "VALUES ('Staff dataset', 'source_dataset', 'mca_csr', false, 'staff-sources/000000000000-x.xlsx') "
        "RETURNING id"
    ).fetchone()["id"]
    assert _sees(conn, _who(world, name), "SELECT 1 FROM documents WHERE id = %s", (doc,)) == expected
```

Append to `backend/tests/test_vault.py`:

```python
@pytest.mark.integration
class TestAStaffDatasetIsStaffOnly:
    async def test_an_org_admin_cannot_read_it_and_staff_can(self, db, org):
        doc = await repo.insert_source_dataset(
            _PoolOf(db), title="Staff dataset · mca_csr · test", source_key="mca_csr",
            storage_path="staff-sources/000000000000-test.xlsx",
            source_url="https://staff-sources.sangam.invalid/000000000000", content_hash="0" * 64,
            extractor_version="source_layouts/mca_csr_analytics_report@00000000", as_of=None,
        )
        await db.execute("UPDATE org_members SET role = 'admin' WHERE user_id = %s", (MEMBER,))
        assert await repo.readable_document(_PoolOf(db), document_id=doc, user_id=MEMBER) is None
        await db.execute("UPDATE users SET is_staff = true WHERE id = %s", (OUTSIDER,))
        assert (await repo.readable_document(_PoolOf(db), document_id=doc, user_id=OUTSIDER))["id"] == doc

    async def test_the_dataset_row_holds_no_content(self, db, org):
        doc = await repo.insert_source_dataset(
            _PoolOf(db), title="Staff dataset · mca_csr · test", source_key="mca_csr",
            storage_path="staff-sources/000000000000-test.xlsx",
            source_url="https://staff-sources.sangam.invalid/000000000000", content_hash="1" * 64,
            extractor_version="source_layouts/mca_csr_analytics_report@00000000", as_of=None,
        )
        row = await (await db.execute(
            "SELECT content_md, is_public, org_id, funder_id, doc_type FROM documents WHERE id = %s", (doc,)
        )).fetchone()
        assert row == {"content_md": None, "is_public": False, "org_id": None, "funder_id": None,
                       "doc_type": "source_dataset"}
        chunks = await (await db.execute("SELECT count(*) AS n FROM chunks WHERE document_id = %s", (doc,))).fetchone()
        assert chunks["n"] == 0
        listed = await repo.list_source_datasets(_PoolOf(db), source_keys=["mca_csr"])
        assert doc in [d["id"] for d in listed]
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_staff_sources.py -q`
Expected: `ModuleNotFoundError: No module named 'app.ingest.staff_sources'`.

- [ ] **Step 3: Add the repository functions**

Append to `backend/app/repositories/documents.py`:

```python
async def insert_source_dataset(
    pool: AsyncConnectionPool, *, title: str, source_key: str, storage_path: str, source_url: str,
    content_hash: str, extractor_version: str, as_of: str | None,
) -> int:
    """A staff dataset's documents row: private, nobody's, and empty.

    No content_md and no chunks, ever. The SQL tool runs as the owner and its catalog lists
    documents.content_md, so text stored here would reach every Ask user. The bytes stay in the
    staff-sources bucket, and read_source_rows is their one reader. The title is deliberately
    neutral, because the catalog shows it too.
    """
    sql = """
    INSERT INTO documents (org_id, funder_id, title, doc_type, source_url, source_name, fetched_at,
                           content_hash, extractor_version, as_of, storage_path, is_public, status)
    VALUES (NULL, NULL, %(title)s, 'source_dataset', %(url)s, %(key)s, now(), %(hash)s, %(version)s,
            %(as_of)s, %(path)s, false, 'received')
    RETURNING id
    """
    params = {"title": title, "url": source_url, "key": source_key, "hash": content_hash,
              "version": extractor_version, "as_of": as_of, "path": storage_path}
    async with pool.connection() as conn:
        row = await (await conn.execute(sql, params)).fetchone()
    return row["id"]


async def source_dataset_by_hash(pool: AsyncConnectionPool, *, content_hash: str) -> dict | None:
    sql = """
    SELECT id, storage_path FROM documents
    WHERE doc_type = 'source_dataset' AND content_hash = %(hash)s
    ORDER BY id LIMIT 1
    """
    async with pool.connection() as conn:
        return await (await conn.execute(sql, {"hash": content_hash})).fetchone()


async def list_source_datasets(
    pool: AsyncConnectionPool, *, source_keys: list[str] | None = None
) -> list[dict]:
    """Every staff dataset, optionally narrowed by registry key. Staff-only rows by construction."""
    sql = """
    SELECT id, title, source_name, source_url, storage_path, content_hash, extractor_version, as_of
    FROM documents
    WHERE doc_type = 'source_dataset' AND NOT is_public AND org_id IS NULL AND funder_id IS NULL
      AND (%(keys)s::text[] IS NULL OR source_name = ANY(%(keys)s::text[]))
    ORDER BY source_name, id
    """
    async with pool.connection() as conn:
        return await (await conn.execute(sql, {"keys": source_keys})).fetchall()
```

Append to `backend/app/repositories/funders.py`:

```python
def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def name_variants(pool: AsyncConnectionPool, *, match: str, limit: int = 5) -> list[dict]:
    """Funders whose name or an alias contains `match`, with every name they go by.

    read_source_rows searches the staff datasets under all of them: an MCA filer files under its
    registered name, which is often not the name the catalog shows.
    """
    sql = """
    SELECT slug, name, aliases FROM funders
    WHERE name ILIKE %(p)s OR EXISTS (SELECT 1 FROM unnest(aliases) a WHERE a ILIKE %(p)s)
    ORDER BY similarity(name, %(m)s) DESC, id
    LIMIT %(limit)s
    """
    async with pool.connection() as conn:
        return await (await conn.execute(sql, {"p": _like(match), "m": match, "limit": limit})).fetchall()
```

`similarity()` needs `pg_trgm`, which `funders_name_trgm` in `02_schema.sql` already requires.

- [ ] **Step 4: Write `staff_sources.py` (read path)**

Create `backend/app/ingest/staff_sources.py`:

```python
"""Staff-only source datasets: where they are kept, how a row is found, how it is cited.

Spreadsheets a person uploaded by hand (scripts/upload_staff_source.py): statutory CSR filings,
and a CSO funder workbook shared under partner permission. Each lives in the private
staff-sources bucket, beside a sidecar of its rows normalised once at upload, with a documents
row holding no content - so the SQL tool, which runs as the owner, cannot read them. Only
read_source_rows reads them, and only the staff-only Import route runs that.

Nothing here logs a value from a row. These files are confidential.
"""

from __future__ import annotations

import asyncio
import gzip
import io
import json
import logging
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from typing import Any

from app.ingest import source_layouts as layouts
from app.ingest.research_records import FISCAL_YEAR
from app.ingest.sources import SOURCES
from app.integrations import storage
from app.repositories import documents as documents_repo
from app.repositories import funders as funders_repo

logger = logging.getLogger(__name__)

DOC_TYPE = "source_dataset"
SOURCE_URL_PREFIX = "https://staff-sources.sangam.invalid/"
SIDECAR_SUFFIX = ".rows.jsonl.gz"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_LIMIT = 2000
# Bounded by bytes, not entries: staging holds a dozen or more datasets (one per split year sheet)
# and every search walks all of them, so a small entry cap would miss on every call.
_CACHE_MAX_BYTES = 200 * 1024 * 1024
_cache: OrderedDict[str, bytes] = OrderedDict()

LABEL = {
    "company": "company", "funder": "funder", "cso": "CSO", "partner": "partner", "project": "project",
    "filed_sector": "filed sector", "funder_type": "type", "role": "role", "purpose": "purpose",
    "outlay": "outlay", "amount": "amount", "avg_net_profit": "average net profit",
    "prescribed_csr": "prescribed CSR", "csr_spent": "CSR spent", "local_area_spent": "local-area spent",
}


def object_key(data: bytes, stored_name: str) -> str:
    return f"{storage.content_hash(data)[:12]}-{stored_name}"


def source_url(data: bytes) -> str:
    """What a finding cites as its source_url: http(s), as findings require, and resolvable by
    nothing (RFC 2606 .invalid). No file name, because it lands in public provenance columns."""
    return SOURCE_URL_PREFIX + storage.content_hash(data)[:12]


def is_staff_source_url(url: str | None) -> bool:
    return bool(url) and str(url).startswith(SOURCE_URL_PREFIX)


def sidecar_key(key: str, profile: layouts.LayoutProfile) -> str:
    """Keyed by the profile's digest: edit a profile and every sidecar it made is stale."""
    return f"{key}.{profile.digest}{SIDECAR_SUFFIX}"


def encode_rows(rows: Iterable[layouts.SourceRow]) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as gz:
        for row in rows:
            gz.write(json.dumps(row.to_json(), ensure_ascii=False).encode("utf-8") + b"\n")
    return buffer.getvalue()


def decode_rows(blob: bytes, terms: list[str]) -> Iterator[layouts.SourceRow]:
    """Only the rows whose names match. A byte test on the padded search key runs first,
    so a 100k-line sidecar is not JSON-parsed line by line."""
    needles = [f" {t} ".encode() for t in terms]
    with gzip.GzipFile(fileobj=io.BytesIO(blob)) as gz:
        for line in gz:
            if not any(n in line for n in needles):
                continue
            row = layouts.SourceRow.from_json(json.loads(line))
            if any(layouts.name_matches(name, terms) for name in row.names()):
                yield row


async def _rows_blob(doc: dict[str, Any], profile: layouts.LayoutProfile) -> tuple[bytes | None, str]:
    parts = storage.split(doc["storage_path"] or "")
    if parts is None or parts[0] != storage.STAFF_SOURCES:
        return None, "its storage_path is not in staff-sources"
    bucket, key = parts
    side = sidecar_key(key, profile)
    if side in _cache:
        _cache.move_to_end(side)
        return _cache[side], "sidecar (cached)"
    blob = await storage.download(bucket, side)
    how = "sidecar"
    if blob is None:
        data = await storage.download(bucket, key)
        if data is None:
            return None, "could not be downloaded from Storage"
        blob = await asyncio.to_thread(lambda: encode_rows(layouts.iter_rows(data, profile)))
        how = "parsed from the workbook (no current sidecar - re-run make staff-source to rebuild it)"
    _cache[side] = blob
    while len(_cache) > 1 and sum(len(b) for b in _cache.values()) > _CACHE_MAX_BYTES:
        _cache.popitem(last=False)
    return blob, how


def _inr(money: layouts.Money) -> str:
    if money.rupees is None:
        return f"not stated (as printed: {money.raw!r})" if money.raw else "blank"
    whole = money.rupees == money.rupees.to_integral_value()
    figure = f"₹{int(money.rupees):,}" if whole else f"₹{money.rupees:,.2f}"
    return f"{figure} (as printed: {money.raw!r} {money.unit})"


def _cite(doc_id: int, row: layouts.SourceRow) -> str:
    return f"[source:{doc_id}#{row.sheet}:{row.cell}]"


def _year(row: layouts.SourceRow) -> str:
    return row.fiscal_year or (f"period {row.period!r}" if row.period else "no year")


def render_row(doc_id: int, row: layouts.SourceRow) -> str:
    parts = [_cite(doc_id, row), _year(row)]
    for f in ("company", "funder", "cso", "partner", "project", "filed_sector", "funder_type", "role", "purpose"):
        if f in row.text:
            parts.append(f"{LABEL[f]} {row.text[f]!r}")
    place = " / ".join(x for x in (row.text.get("state"), row.text.get("district")) if x)
    if place:
        parts.append(f"place {place}")
    if "company_state" in row.text:
        parts.append(f"filer's state {row.text['company_state']}")
    if row.mode:
        filed = row.text.get("implementation_mode")
        parts.append(f"mode {row.mode}" + (f" (as filed: {filed!r})" if filed else ""))
    for f in ("outlay", "amount"):
        if f in row.money:
            parts.append(f"{LABEL[f]} {_inr(row.money[f])}")
    parts += [f"{label}: {value!r}" for label, value in row.details.items()]
    parts += [f"{label}: {value!r}" for label, value in row.context.items() if label != "note"]
    return " · ".join(parts)


def render_company_year(doc_id: int, row: layouts.SourceRow) -> str:
    figures = " · ".join(
        f"{LABEL[f]} {_inr(row.money[f])}" for f in layouts.COMPANY_YEAR_FIELDS if f in row.money
    )
    return (f"{_cite(doc_id, row)} {_year(row)} · company-year {row.text.get('company')!r} · {figures} "
            f"(the filing repeats these on every project line; stated once here)")


def _sheet_heading(sheet: str, note: str | None) -> str:
    """Every sheet is cited and saved alike (D14); its own note, e.g. a unit or a caveat, travels."""
    return f"### sheet {sheet!r}" + (f"\nSheet note: {note}" if note else "")


async def search(
    pool: Any, match: str, *, source_keys: list[str] | None = None,
    fiscal_years: list[str] | None = None, limit: int = 500,
) -> str:
    match = (match or "").strip()
    if len(layouts.normalise_name(match)) < 3:
        return "read_source_rows needs a name of at least three letters to look for."
    years = [y.strip() for y in (fiscal_years or []) if y and y.strip()]
    bad = [y for y in years if not FISCAL_YEAR.match(y)]
    if bad:
        return f"read_source_rows: fiscal years are written FY2023-24, not {', '.join(map(repr, bad))}."
    unknown = [k for k in (source_keys or []) if k not in SOURCES]
    if unknown:
        return f"read_source_rows: {', '.join(unknown)} is not a registered source key."
    limit = max(1, min(int(limit or 500), MAX_LIMIT))

    funders = await funders_repo.name_variants(pool, match=match)
    terms = layouts.search_terms([match, *(n for f in funders for n in (f["name"], *(f["aliases"] or [])))])
    datasets = await documents_repo.list_source_datasets(pool, source_keys=source_keys or None)
    if not datasets:
        scope = f" under {', '.join(source_keys)}" if source_keys else ""
        return (f"No staff dataset is uploaded{scope}. A person adds one with make staff-source "
                f"(scripts/upload_staff_source.py). Nothing was read.")

    body: list[str] = []
    problems: list[str] = []
    matched: dict[str, str] = {}
    shown = total = left_out = with_rows = 0
    for doc in datasets:
        try:
            profile = layouts.profile_from_version(doc["extractor_version"])
            blob, how = await _rows_blob(doc, profile)
            if blob is None:
                problems.append(f"document {doc['id']} ({doc['source_name']}) could not be read: {how}")
                continue
            rows = await asyncio.to_thread(lambda b=blob: list(decode_rows(b, terms)))
        except (layouts.LayoutError, OSError, ValueError) as exc:
            problems.append(f"document {doc['id']} ({doc['source_name']}) could not be read: {exc}")
            continue
        if years:
            left_out += sum(1 for r in rows if r.fiscal_year is None)
            rows = [r for r in rows if r.fiscal_year in years]
        if not rows:
            continue
        with_rows += 1
        company_years = {id(r) for r in layouts.company_years(rows)}
        total += len(rows) + len(company_years)
        lines = [f"## document {doc['id']} · {doc['source_name']} · {doc['title']}",
                 f"source_url for a finding: {doc['source_url']} · source_name: {doc['source_name']} "
                 f"· read from: {how}"]
        sheet = None
        for row in rows:
            for name in row.names():
                matched.setdefault(name, doc["source_name"])
            if row.sheet != sheet:
                sheet = row.sheet
                lines.append(_sheet_heading(sheet, row.context.get("note")))
            for line in ([render_company_year(doc["id"], row)] if id(row) in company_years else []) + [
                render_row(doc["id"], row)
            ]:
                if shown < limit:
                    lines.append(line)
                    shown += 1
        body.append("\n".join(lines))

    logger.info("read_source_rows: %d of %d lines from %d of %d datasets", shown, total, with_rows, len(datasets))
    searched = "; ".join(terms)
    if not body:
        text = (f"No row in {len(datasets)} staff datasets names {match!r} (searched: {searched}). The MCA "
                f"filer is often the parent company, not the foundation: try the registered company name.")
        return "\n".join([text, *problems])
    via = ", ".join(f"funder {f['slug']!r}" for f in funders)
    head = [
        f"read_source_rows: {shown} of {total} lines for {match!r}, from {with_rows} of {len(datasets)} "
        f"staff datasets.",
        "Names matched: " + "; ".join(f"{n} ({k})" for n, k in list(matched.items())[:20]),
        f"Searched for: {searched}" + (f" (aliases from {via})" if via else ""),
        "Amounts are rupees; the figure as printed and its unit follow each one. Save the printed "
        "figure and unit, never the rupee figure. Cite each fact by its [source:…] marker.",
    ]
    tail = []
    if total > shown:
        tail.append(f"{total - shown} more rows not shown (limit {limit}) — narrow with fiscal_years or source_keys.")
    if left_out:
        tail.append(f"{left_out} rows give a period rather than one fiscal year and were left out by the "
                    f"year filter; call again without fiscal_years to see them.")
    return "\n\n".join(["\n".join(head), *body, *(["\n".join(tail)] if tail else []), *problems])
```

`research_records.FISCAL_YEAR` is the existing `^FY\d{4}-\d{2}$` regex. Importing it keeps one definition.

- [ ] **Step 5: Run the tests**

Run: `cd backend && pytest tests/test_staff_sources.py -q`
Expected: all pass.

Run: `cd backend && pytest tests/test_rls.py tests/test_vault.py -q -m integration` (needs `make up`, `make migrate` and (b) merged)
Expected: the six `test_a_staff_dataset_reaches_only_staff` cases and `TestAStaffDatasetIsStaffOnly` pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingest/staff_sources.py backend/app/repositories/documents.py backend/app/repositories/funders.py backend/tests/test_staff_sources.py backend/tests/test_rls.py backend/tests/test_vault.py
git commit -m "feat(ingest): read staff datasets by name, every sheet, cited and in rupees

Rows come from a sidecar normalised once at upload, keyed by the profile's digest;
a stale one falls back to the workbook. Every sheet is cited alike. The dataset
row holds no content, and RLS gives it to staff alone.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The upload script

**Files:**
- Modify: `backend/app/ingest/staff_sources.py` (add `register_dataset`, `Registered`)
- Create: `scripts/upload_staff_source.py`
- Modify: `Makefile`
- Test: `backend/tests/test_staff_sources.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class Registered: document_id: int; storage_path: str; status: str; rows: int
async def register_dataset(pool, data: bytes, filename: str, source_key: str, *,
                           part: str | None = None) -> Registered
```

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_staff_sources.py`:

```python
class _Uploads:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def __call__(self, bucket, key, data, content_type, *, replace=False):
        assert bucket == "staff-sources"
        self.objects[key] = data
        return key


@pytest.fixture
def uploads(monkeypatch):
    up = _Uploads()
    inserted: list[dict] = []

    async def by_hash(pool, *, content_hash):
        return next(({"id": d["id"], "storage_path": d["storage_path"]} for d in inserted
                     if d["content_hash"] == content_hash), None)

    async def insert(pool, **kw):
        inserted.append({"id": 100 + len(inserted), **kw})
        return inserted[-1]["id"]

    monkeypatch.setattr(staff_sources.storage, "upload", up)
    monkeypatch.setattr(staff_sources.documents_repo, "source_dataset_by_hash", by_hash)
    monkeypatch.setattr(staff_sources.documents_repo, "insert_source_dataset", insert)
    return up, inserted


async def test_an_upload_stores_the_workbook_its_sidecar_and_a_private_row(uploads):
    up, inserted = uploads
    result = await staff_sources.register_dataset(object(), cso_workbook(), CSO_NAME, "ffrh_funder_datasets")
    key = result.storage_path.partition("/")[2]
    assert result.status == "added" and result.rows > 0
    assert set(up.objects) == {key, staff_sources.sidecar_key(key, CSO)}
    assert key.endswith("-cso_programmes_and_funders.xlsx")   # the profile's name, not the original file's
    row = inserted[0]
    assert row["source_key"] == "ffrh_funder_datasets"
    assert row["extractor_version"] == CSO.version
    assert row["source_url"].startswith(staff_sources.SOURCE_URL_PREFIX)
    assert "Details of programs" not in row["title"] and "Details of programs" not in row["storage_path"]


async def test_the_same_bytes_twice_is_one_row(uploads):
    _, inserted = uploads
    data = cso_workbook()
    await staff_sources.register_dataset(object(), data, CSO_NAME, "ffrh_funder_datasets")
    again = await staff_sources.register_dataset(object(), data, CSO_NAME, "ffrh_funder_datasets")
    assert again.status == "matched" and len(inserted) == 1


async def test_the_upload_refuses_an_unprofiled_sheet(uploads):
    up, inserted = uploads
    with pytest.raises(layouts.LayoutError, match="'Summary' has no entry"):
        await staff_sources.register_dataset(object(), analytics_report(extra_sheet="Summary"), ANALYTICS_NAME,
                                             "mca_csr")
    assert not up.objects and not inserted


async def test_a_split_part_keeps_its_sheet_in_the_key(uploads):
    _, inserted = uploads
    for sheet, part in layouts.split_by_sheet(analytics_report()):
        await staff_sources.register_dataset(object(), part, ANALYTICS_NAME, "mca_csr", part=sheet)
    assert [d["as_of"] for d in inserted] == ["2022-23", "2023-24"]
    assert inserted[1]["storage_path"].endswith("-mca_csr_analytics_report--2023-24.xlsx")


async def test_an_unregistered_key_is_refused(uploads):
    with pytest.raises(ValueError, match="not a registered source key"):
        await staff_sources.register_dataset(object(), cso_workbook(), CSO_NAME, "nope")


def test_the_script_is_a_thin_wrapper():
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "scripts" / "upload_staff_source.py").read_text()
    calls = {n.attr for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Attribute)}
    assert "register_dataset" in calls and "split_by_sheet" in calls
    assert "print(row" not in source   # it reports counts, never rows
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_staff_sources.py -q -k "upload or split or unregistered or script or same_bytes"`
Expected: `AttributeError: module 'app.ingest.staff_sources' has no attribute 'register_dataset'`.

- [ ] **Step 3: Add `register_dataset`**

Append to `backend/app/ingest/staff_sources.py`. Also add `from dataclasses import dataclass` to the imports.

```python
@dataclass(frozen=True)
class Registered:
    document_id: int
    storage_path: str
    status: str          # added | matched
    rows: int


def _safe_part(part: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in part)


async def register_dataset(
    pool: Any, data: bytes, filename: str, source_key: str, *, part: str | None = None
) -> Registered:
    """Parse, store and record one staff dataset. Raises: this is a staff script's path, not a tool.

    The parse comes first and is total. An unprofiled sheet or a drifted header stops the upload
    before a byte reaches Storage, which is where D13's "fail loudly" has to bite. The original
    file name is used only to choose the profile; the key and the title carry the profile's name.
    """
    if source_key not in SOURCES:
        raise ValueError(f"{source_key!r} is not a registered source key")
    profile = layouts.profile_for(source_key, filename)
    counted: list[int] = [0]

    def parse() -> bytes:
        def counting() -> Iterator[layouts.SourceRow]:
            for row in layouts.iter_rows(data, profile):
                counted[0] += 1
                yield row

        return encode_rows(counting())

    blob = await asyncio.to_thread(parse)
    stored = profile.stored_name if part is None else f"{profile.name}--{_safe_part(part)}.xlsx"
    key = object_key(data, stored)
    if await storage.upload(storage.STAFF_SOURCES, key, data, XLSX) is None:
        raise RuntimeError(f"storing {key} failed - is Storage configured, and is the file under 50 MB?")
    if await storage.upload(storage.STAFF_SOURCES, sidecar_key(key, profile), blob, "application/gzip",
                            replace=True) is None:
        raise RuntimeError(f"storing the rows of {key} failed")
    path = storage.qualify(storage.STAFF_SOURCES, key)
    digest = storage.content_hash(data)
    existing = await documents_repo.source_dataset_by_hash(pool, content_hash=digest)
    if existing:
        return Registered(existing["id"], existing["storage_path"], "matched", counted[0])
    title = f"Staff dataset · {source_key} · {profile.name}" + (f" · sheet {part}" if part else "")
    document_id = await documents_repo.insert_source_dataset(
        pool, title=title, source_key=source_key, storage_path=path, source_url=source_url(data),
        content_hash=digest, extractor_version=profile.version, as_of=part,
    )
    logger.info("staff dataset %s stored as document %d (%d rows)", path, document_id, counted[0])
    return Registered(document_id, path, "added", counted[0])
```

The sidecar upload uses `replace=True`. A profile fix re-run with the same bytes then rewrites the sidecar under its new digest key; the old one is simply unused.

- [ ] **Step 4: Write the script**

Create `scripts/upload_staff_source.py`:

```python
"""Upload one staff-only dataset to the private staff-sources bucket.

    make staff-source FILE="<path>.xlsx" KEY=mca_csr [SPLIT=1] [ENV=staging]

One-off and staff-run, with the service key: a `require_staff` upload route can replace it.
Prints what it stored and how many rows it read - never a row. The file must match exactly
one layout profile in backend/app/ingest/data/source_layouts/, and every sheet in it must have
an entry there, or nothing is stored.

A workbook over the 50 MB bucket limit is stored one sheet per object with --split-sheets
(table-layout profiles only: a split keeps values, not merged cells).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.core.config import get_settings
from app.db.checkpointer import make_pool
from app.ingest import source_layouts, staff_sources
from app.integrations import storage


async def main(path: Path, source_key: str, split: bool) -> int:
    settings = get_settings()
    if not settings.storage_enabled:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set: staff datasets live only in Storage.")
        return 2
    data = path.read_bytes()
    profile = source_layouts.profile_for(source_key, path.name)
    if split and profile.load != "read_only":
        print(f"{profile.name} has block or section sheets; splitting would lose their merged cells.")
        return 2
    if len(data) > storage.MAX_ARCHIVE_BYTES and not split:
        print(f"{len(data) / 1024 / 1024:.1f} MB is over the 50 MB bucket limit. Re-run with SPLIT=1: "
              f"one object per sheet, each read by the same profile.")
        return 2
    parts = source_layouts.split_by_sheet(data) if split else [(None, data)]
    pool = make_pool(settings.database_url, max_size=2)
    await pool.open()
    try:
        for part, blob in parts:
            result = await staff_sources.register_dataset(pool, blob, path.name, source_key, part=part)
            print(f"{result.status}: document {result.document_id} · {result.storage_path} · {result.rows} rows")
    finally:
        await pool.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path)
    parser.add_argument("--source-key", required=True, help="registry key, e.g. mca_csr")
    parser.add_argument("--split-sheets", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.file, args.source_key, args.split_sheets)))
```

- [ ] **Step 5: Add the Makefile target**

Add `staff-source` to the `.PHONY` line. After the `client-docs` target, add:

```make
# Upload one staff-only dataset (spec §4). Host venv, like client-docs: the image mounts only
# app/, seed/ and db/, and the file lives on this machine. Honours ENV for the database; Storage
# comes from SUPABASE_URL / SUPABASE_SERVICE_KEY in .env.
staff-source:  ## Upload a staff dataset: make staff-source FILE="<xlsx>" KEY=<registry key> [SPLIT=1]
	@test -n "$(FILE)" && test -n "$(KEY)" || { echo 'usage: make staff-source FILE="<xlsx>" KEY=<key> [SPLIT=1]'; exit 2; }
	@set -a; [ -f .env ] && . ./.env; set +a; \
	DATABASE_URL="$(if $(filter staging,$(ENV)),$(DB_URL),postgresql://sangam:sangam@localhost:5433/sangam)" \
	PYTHONPATH=backend backend/.venv/bin/python scripts/upload_staff_source.py "$(FILE)" \
	  --source-key "$(KEY)" $(if $(SPLIT),--split-sheets,)
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest tests/test_staff_sources.py -q`
Expected: all pass.

Run: `make staff-source FILE=/dev/null KEY=mca_csr`
Expected: exit 2, with the Storage message (locally) or a `LayoutError` naming the profile mismatch.

- [ ] **Step 7: Commit**

```bash
git add backend/app/ingest/staff_sources.py scripts/upload_staff_source.py Makefile backend/tests/test_staff_sources.py
git commit -m "feat(scripts): upload a staff dataset - parse, store, record

The whole workbook is parsed before anything is stored, so an unprofiled sheet
stops the upload. Over 50 MB, a table-layout file is stored one sheet per object.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The `read_source_rows` tool, registered on the researcher

**Files:**
- Modify: `backend/app/ingest/tools/pipeline_tools.py`, `backend/app/ingest/agent.py`
- Modify: `backend/app/ingest/prompts/entity_researcher.md`, `backend/app/ingest/instructions.md`
- Modify: `frontend/features/ingest/lib/toolLabels.ts`
- Modify: `docs/INGEST.md`
- Test: `backend/tests/test_staff_sources.py`, `backend/tests/test_harness.py`, `backend/tests/test_ingest.py`

**Interfaces:**

```python
@tool
async def read_source_rows(match: str, source_keys: list[str] | str | None = None,
                           fiscal_years: list[str] | str | None = None, limit: int = 500) -> str
```

**Where it goes:** on `entity-researcher` (`RESEARCH_TOOLS`), not on the supervisor's `TOOLS`. The supervisor "researches nothing" (agent.py, `docs/INGEST.md`). The researcher is the only agent that runs `save_research`, and it works under the money-unit, entity-confirmation and budget rules. A second copy on the supervisor would be the "two paths to the same work" that CLAUDE.md removed. The supervisor's prompt names the tool in "Tools you do NOT have", so the skill it loads can tell it what to ask for.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_staff_sources.py`:

```python
from app.ingest.tools import pipeline_tools


async def test_the_tool_passes_its_arguments_through(monkeypatch):
    seen = {}

    async def fake(pool, match, *, source_keys=None, fiscal_years=None, limit=500):
        seen.update(match=match, source_keys=source_keys, fiscal_years=fiscal_years, limit=limit)
        return "ok"

    monkeypatch.setattr(pipeline_tools, "get_pool", lambda: object())
    monkeypatch.setattr(pipeline_tools.staff_sources, "search", fake)
    out = await pipeline_tools.read_source_rows.ainvoke(
        {"match": "Kestrel", "source_keys": "mca_csr, ffrh_funder_datasets", "fiscal_years": ["FY2023-24"]}
    )
    assert out == "ok"
    assert seen == {"match": "Kestrel", "source_keys": ["mca_csr", "ffrh_funder_datasets"],
                    "fiscal_years": ["FY2023-24"], "limit": 500}


async def test_the_tool_never_raises(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("pool exhausted")

    monkeypatch.setattr(pipeline_tools, "get_pool", lambda: object())
    monkeypatch.setattr(pipeline_tools.staff_sources, "search", boom)
    out = await pipeline_tools.read_source_rows.ainvoke({"match": "Kestrel"})
    assert out == "read_source_rows failed: pool exhausted"


def test_read_source_rows_is_the_researchers_not_the_supervisors():
    from app.ingest.agent import CATALOG_WRITER, ENTITY_RESEARCHER, INSTRUCTIONS, TOOLS

    assert "read_source_rows" in {t.name for t in ENTITY_RESEARCHER["tools"]}
    assert "read_source_rows" not in {t.name for t in TOOLS}
    assert "read_source_rows" not in {t.name for t in CATALOG_WRITER["tools"]}
    # the supervisor is told it exists and whose it is
    assert "`read_source_rows`" in INSTRUCTIONS


def test_the_researcher_is_told_to_quote_the_marker():
    from app.ingest.agent import ENTITY_RESEARCHER

    prompt = ENTITY_RESEARCHER["system_prompt"]
    assert "read_source_rows" in prompt and "marker included" in prompt
    assert "`partner` finding" in prompt and "`amount`" in prompt


def test_the_frontend_labels_the_tool():
    from pathlib import Path

    labels = Path(__file__).resolve().parents[2] / "frontend" / "features" / "ingest" / "lib" / "toolLabels.ts"
    assert "read_source_rows:" in labels.read_text()
```

In `backend/tests/test_harness.py`, replace `test_the_researcher_gets_its_seven_and_nothing_of_the_filesystem` with:

```python
    def test_the_researcher_gets_its_eight_and_nothing_of_the_filesystem(self, subagents):
        assert subagents["entity-researcher"] == {
            "research_goals", "funder_dossier", "read_source_rows", "search_public_sources",
            "read_page", "fetch_document", "read_document_pages", "save_research",
            "read_file",
        }
```

In `backend/tests/test_ingest.py`, in `TestTheCatalogWriterCannotResearch.test_it_holds_no_research_tools`, extend the forbidden set:

```python
        assert not names & {"search_public_sources", "read_page", "fetch_document",
                            "read_document_pages", "save_research", "read_source_rows"}
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_staff_sources.py tests/test_harness.py tests/test_ingest.py -q -k "tool or researcher or frontend or writer"`
Expected: `AttributeError: module 'app.ingest.tools.pipeline_tools' has no attribute 'read_source_rows'`, plus the researcher set mismatch.

- [ ] **Step 3: Add the tool**

In `backend/app/ingest/tools/pipeline_tools.py`:

- add `from app.ingest import staff_sources` to the imports;
- replace the module docstring's first paragraph with:

```python
"""The adapter path: the source registry, the runs that pull from it, and the staff datasets.

One tool per step of a write-run — see which sources may be read, say what a
run would pull, run it, read the summary back, and see what it queued for a
person — plus read_source_rows, for the spreadsheets a person uploaded by hand
(the manual-entry side of the same registry). Like every Sangam tool, they
return errors, never raise."""
```

Append:

```python
def _as_list(value: list[str] | str | None) -> list[str] | None:
    if value is None:
        return None
    items = value.split(",") if isinstance(value, str) else value
    cleaned = [str(v).strip() for v in items if str(v).strip()]
    return cleaned or None


@tool
async def read_source_rows(
    match: str,
    source_keys: list[str] | str | None = None,
    fiscal_years: list[str] | str | None = None,
    limit: int = 500,
) -> str:
    """Read the staff-only datasets — statutory CSR filings and the CSO funder workbook — for one name.

    Reads every staff dataset and every sheet in each, through its layout profile, and
    returns the rows whose company, funder or CSO name matches `match` or one of the
    catalog's aliases for that funder. Read this BEFORE the web for a corporate funder:
    it is the statutory filing itself.

    Amounts come back in rupees with the figure as printed and its unit beside them. Save
    the printed figure and unit ({value: 0.36, unit: 'crore'}), never the rupee figure.
    Company-level figures (net profit, prescribed CSR, spent, local-area) are stated once
    per company-year; never add them up across project lines.

    Cite every fact by its row's [source:<document>#<sheet>:<cell>] marker. A finding from
    a row uses the dataset's source_url and source_name, printed at the head of each
    dataset, and quotes the row's line as its evidence.

    Every sheet is citable. A finding from a row quotes the row's line, marker included;
    promotion holds a staff-dataset finding without its marker. A grant amount from a CSO
    funder sheet is saved on a `partner` finding (funder, CSO as partner_name, year, amount).

    The MCA filer is often the parent company, not the foundation: search both names.

    Args:
        match: a name, at least three letters. The filer's registered name is best.
        source_keys: registry keys to narrow to, e.g. ["mca_csr"]. Default: every staff dataset.
        fiscal_years: e.g. ["FY2023-24"]. Rows giving a period rather than one fiscal year
            are left out by this filter, and counted.
        limit: most lines returned (default 500).
    """
    try:
        return await staff_sources.search(
            get_pool(), match, source_keys=_as_list(source_keys), fiscal_years=_as_list(fiscal_years),
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001 - a tool returns its failure, never raises it
        return f"read_source_rows failed: {exc}"
```

- [ ] **Step 4: Register it on the researcher**

In `backend/app/ingest/agent.py`, add `read_source_rows` to the `pipeline_tools` import list, then:

```python
RESEARCH_TOOLS = [
    research_goals,
    funder_dossier,
    # The staff datasets before the web: for a corporate funder they are the statutory
    # filing itself. Staff-only by the route this agent sits behind (require_staff).
    read_source_rows,
    search_public_sources,
    read_page,
    fetch_document,
    read_document_pages,
]
```

- [ ] **Step 5: Name it in the researcher's prompt**

In `backend/app/ingest/prompts/entity_researcher.md`:

(a) After the paragraph that begins `**STEP 2: \`research_goals(name, entity_kind)\`.**`, insert:

```markdown
**For a corporate funder, read the staff datasets before the web: `read_source_rows(match)`.** They hold the statutory CSR filings, every sheet of every file, under the filer's registered name — often the parent company, not the foundation, so search both. Each row comes with a `[source:<document>#<sheet>:<cell>]` marker; a finding from it uses the dataset's `source_url` and `source_name` printed above it, and quotes the row's line as its evidence. Save the amount **as printed, with its unit** — the rupee figure beside it is for reading, not for saving. The company-year line states the obligation and spend once; never add them up across project lines. Every sheet is citable, the CSO funder sheets included: a finding from any row quotes the row's line, marker included — without the marker, promotion holds it, because the dataset's `source_url` alone does not say which sheet and cell the fact came from. A grant amount from a CSO funder sheet goes on a `partner` finding for the funder: the CSO as `partner_name`, the fiscal year, and the `amount` as printed with its unit (`{value: 7.5, unit: 'lakh'}`); promotion normalises it to rupees on the `kind = 'partner'` line. Calls to it do not count against your document budget.
```

(b) In "## Your tools", insert before the `save_research` bullet:

```markdown
- `read_source_rows(match, source_keys, fiscal_years, limit)` — the staff datasets: statutory CSR
  filings and the CSO funder workbook, every sheet, in rupees beside the figure as printed, every
  row cited. Quote the row's line, marker included, in every finding from it. A CSO funder sheet's
  grant amount is a `partner` finding with its `amount`.
```

- [ ] **Step 6: Tell the supervisor**

In `backend/app/ingest/instructions.md`:

(a) At the end of "## Source priority" (after `…is the error to watch for.`), append:

```markdown

For a corporate funder the strongest source of all is often already here: the staff datasets
hold the statutory CSR filings, and a researcher reads them with `read_source_rows` before the
web. Put the filer's registered name in the task description when you know it — the MCA filer
is often the parent company, not the foundation.
```

(b) In the "Tools you do NOT have" table, replace the researcher row with:

```markdown
| `research_goals` · `read_source_rows` · `search_public_sources` · `read_page` · `fetch_document` · `read_document_pages` · `save_research` | `entity-researcher` |
```

- [ ] **Step 7: Label it in the frontend**

In `frontend/features/ingest/lib/toolLabels.ts`, add after `read_document_pages`:

```ts
  read_source_rows: {
    label: "Reading staff datasets",
    detail: (a) =>
      [a?.match, Array.isArray(a?.fiscal_years) ? a.fiscal_years.join(", ") : a?.fiscal_years]
        .filter(Boolean)
        .join(" · "),
  },
```

- [ ] **Step 8: Document it**

In `docs/INGEST.md`:

- replace the `pipeline_tools.py` table row with:

  ```markdown
  | `pipeline_tools.py` | `list_import_sources` · `plan_import` · `run_import_now` · `import_run_summary` · `pending_resolutions` · `read_source_rows` |
  ```

- after the `**`entity-researcher`**` paragraph, add:

```markdown
**Staff datasets.** `read_source_rows` is the researcher's eighth tool. It reads the spreadsheets a
person uploaded with `make staff-source` — statutory CSR filings and the CSO funder workbook —
from the private `staff-sources` bucket, through a layout profile per file
(`app/ingest/data/source_layouts/`). Every sheet is read; a sheet with no profile entry fails the
upload, not the read. Rows come back in rupees beside the figure as printed, cited
`[source:<document>#<sheet>:<cell>]`. Every sheet is citable, and a fact promoted from one is a
public row like any other (FFRH has cleared the CSO workbook's figures for display); only the
files stay staff-only. `promote` holds a finding that cites a staff dataset without its marker,
because the dataset URL alone does not say which sheet and cell the fact came from. The
documents row of a dataset holds no content, so Ask's SQL tool cannot read it; RLS and
`readable_document` give the row to staff alone. Tool output does reach the model provider and,
when tracing is on, Langfuse, like every tool output.
```

- [ ] **Step 9: Run the tests**

Run: `cd backend && pytest tests/test_staff_sources.py tests/test_harness.py tests/test_ingest.py -q`
Expected: all pass, including `test_a_subagent_prompt_names_every_tool_its_spec_declares[ENTITY_RESEARCHER]` and `test_every_tool_defined_is_also_registered`.

Run: `cd frontend && npm run lint && npm run build`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add backend/app/ingest/tools/pipeline_tools.py backend/app/ingest/agent.py backend/app/ingest/prompts/entity_researcher.md backend/app/ingest/instructions.md frontend/features/ingest/lib/toolLabels.ts docs/INGEST.md backend/tests/test_staff_sources.py backend/tests/test_harness.py backend/tests/test_ingest.py
git commit -m "feat(ingest): read_source_rows on the researcher

The statutory filing before the web, every sheet, cited, in rupees beside the
figure as printed. The supervisor is told whose it is; it researches nothing.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Promotion — staff URLs map to the dataset row; a finding without its marker is held; the FFRH basis

**Files:**
- Modify: `backend/app/ingest/staff_sources.py` (add `hold_unmarked`)
- Modify: `backend/app/ingest/promote.py`
- Modify: `backend/app/ingest/data/sources/funders.json` (`ffrh_funder_datasets.basis`)
- Test: `backend/tests/test_staff_sources.py`

**Interfaces:**

```python
def hold_unmarked(findings: list[dict]) -> tuple[list[dict], list[str]]   # staff_sources.py
async def _staff_datasets(conn, findings: list[dict]) -> dict[str, int]   # promote.py, source_url -> id
```

The §5 acceptance run loads filing lines into `funder_activity` through `read_source_rows`. Promotion therefore has to accept a finding whose `source_url` is a staff URL. It must link that finding to the existing private row, and never add a public one. Every sheet is promotable (D14): a fact from the CSO funder sheets becomes a public row under the same `funder_activity.is_public` default as any other. The one thing held is a staff finding without its `[source:…]` marker: one dataset URL covers every sheet of a file, so without the marker the fact could not be traced to its sheet and cell.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_staff_sources.py`:

```python
from app.ingest import promote
from app.ingest.sources import SOURCES


def _finding(concept, evidence, url="https://staff-sources.sangam.invalid/0123456789ab"):
    return {"concept": concept, "evidence": evidence, "source_url": url}


def test_a_finding_citing_a_cso_funder_sheet_is_kept():
    """D14: the CSO funder sheets are promoted like the filings, as public facts."""
    findings = [
        _finding("partner", "[source:42#CSO Current funder and Partners:A7] period '2023–2024' · funder …"),
        _finding("csr_spend", "[source:41#2023-24:A2] FY2023-24 · company 'Kestrel Polymers Limited' …"),
    ]
    kept, held = staff_sources.hold_unmarked(findings)
    assert kept == findings and held == []


def test_a_staff_finding_without_its_marker_is_held():
    """One dataset URL covers every sheet of a file; no marker, no trail to the sheet and cell."""
    kept, held = staff_sources.hold_unmarked([
        _finding("partner", "the CSO's sheet lists this funder for 2023-24, seven lakh"),
        _finding("grant", "the recipient's annual report names this funder", url="https://example.org/report"),
    ])
    assert [f["concept"] for f in kept] == ["grant"]
    assert held == ["partner: cites a staff dataset without its [source:…] marker — quote the row's line, "
                    "marker included, so the fact traces to its sheet and cell"]


def test_the_ffrh_basis_records_that_the_figures_are_cleared_for_display():
    basis = SOURCES["ffrh_funder_datasets"].basis
    assert "cleared" in basis and "display" in basis
    assert "consent" not in basis


class _Conn:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    async def execute(self, sql, params=()):
        self.sql.append((" ".join(sql.split()), params))
        rows = self.rows

        class _Cursor:
            async def fetchall(self_inner):
                return rows

            async def fetchone(self_inner):
                return rows[0] if rows else None

        return _Cursor()


async def test_a_finding_at_a_staff_url_links_to_the_private_dataset_row():
    url = "https://staff-sources.sangam.invalid/0123456789ab"
    conn = _Conn([{"id": 41, "source_url": url}])
    found = await promote._staff_datasets(conn, [_finding("csr_spend", "x" * 30, url)])
    assert found == {url: 41}
    sql, params = conn.sql[0]
    assert "doc_type = 'source_dataset'" in sql and params == ([url],)


async def test_a_document_finding_at_a_staff_url_adds_no_row(monkeypatch):
    """ensure_document inserts with is_public = true; a staff dataset must never get that row."""
    url = "https://staff-sources.sangam.invalid/0123456789ab"
    doc = type("Doc", (), {"source_url": url, "title": "t", "source_name": None, "as_of": None,
                           "doc_type": "annual_report"})()
    monkeypatch.setattr(promote, "_validated", lambda findings, concept: [doc] if concept == "document" else [])
    calls = []

    async def ensure(*a, **k):
        calls.append(k)
        return 1, "added"

    monkeypatch.setattr(promote, "ensure_document", ensure)
    # One canned row answers both queries: the slug lookup and the staff-dataset lookup.
    conn = _Conn([{"slug": "kestrel-foundation", "id": 41, "source_url": url}])
    by_url = await promote._write_documents(
        conn, {"researched_at": None}, [{"concept": "document", "source_url": url}],
        promote.Owner.funder(1), {"written": {}, "held": []},
    )
    assert calls == []
    assert by_url == {url: 41}
```

`Owner` is `app.ingest.writer.Owner`, imported into `promote`. If (b) moved it, import it from where (b) put it.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_staff_sources.py -q -k "marker or cso_funder_sheet or staff_url or basis"`
Expected: `AttributeError: … has no attribute 'hold_unmarked'` / `'_staff_datasets'`, and the basis test failing on `"cleared" in basis`.

- [ ] **Step 3: Add the marker check**

Append to `backend/app/ingest/staff_sources.py`. Also add `import re` to the imports.

```python
_CITATION = re.compile(r"\[source:\d+#(?P<sheet>[^\]]+):[A-Z]{1,3}\d+\]")


def hold_unmarked(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Findings that may be promoted, and a held reason for each one that may not.

    Every sheet of every staff dataset is promotable (D14). What is not is a finding that cites
    a staff dataset's URL without the row's [source:<document>#<sheet>:<cell>] marker: one URL
    covers every sheet of a file, so the promoted row could not be traced to its sheet and cell,
    and every field has to trace to a source.
    """
    kept: list[dict[str, Any]] = []
    held: list[str] = []
    for f in findings:
        if is_staff_source_url(f.get("source_url")) and not _CITATION.search(str(f.get("evidence", ""))):
            held.append(
                f"{f.get('concept')}: cites a staff dataset without its [source:…] marker — quote the "
                f"row's line, marker included, so the fact traces to its sheet and cell"
            )
        else:
            kept.append(f)
    return kept, held
```

- [ ] **Step 4: Wire it into `promote.py`**

Add `from app.ingest import staff_sources` to the imports.

In `promote()`, right after the `schema_version` check and its `return report`, insert:

```python
    findings, unmarked = staff_sources.hold_unmarked(findings)
    report["held"].extend(unmarked)
```

In `_write_documents`, make the first statement inside `for f in _validated(findings, "document"):` the following:

```python
        if staff_sources.is_staff_source_url(f.source_url):
            # A staff dataset already has its documents row - private, written by the upload
            # script. ensure_document would add a second one, with is_public = true.
            continue
```

Replace its final `return by_url` with:

```python
    by_url.update(await _staff_datasets(conn, findings))
    return by_url


async def _staff_datasets(conn: Any, findings: list[dict[str, Any]]) -> dict[str, int]:
    """source_url -> the private documents row of each staff dataset these findings cite, so a
    filing line written from read_source_rows carries its document_id like any other."""
    urls = sorted({f["source_url"] for f in findings if staff_sources.is_staff_source_url(f.get("source_url"))})
    if not urls:
        return {}
    rows = await (await conn.execute(
        "SELECT id, source_url FROM documents WHERE doc_type = 'source_dataset' AND source_url = ANY(%s) "
        "ORDER BY id",
        (urls,),
    )).fetchall()
    found: dict[str, int] = {}
    for row in rows:
        found.setdefault(row["source_url"], row["id"])
    return found
```

Every writer already resolves `docs.get(f.source_url)`. A spend, csr-year, partner or programme finding citing a staff URL therefore now carries `document_id` = the dataset row. Its `source_url` is the non-identifying `.invalid` URL, and its `source_name` is the registry key. It is written with the writers' default, `is_public = true`: the fact is public, the file it came from is not.

- [ ] **Step 5: Record FFRH's clearance in the registry**

In `backend/app/ingest/data/sources/funders.json`, in the `ffrh_funder_datasets` entry, replace the `basis` value with:

```json
      "basis": "Shared by FFRH for this project through Drive. Use follows the FFRH agreement; FFRH has cleared its figures, funder-CSO links and grant amounts included, for display. The files stay in the staff-only bucket; facts promoted from them are public.",
```

Leave `access_rule` (`partner_permission_internal`), `categories`, `yields` and `robots_checked_at` as they are: the rule governs reading the files, which stays staff-only, and `DISPATCHABLE` is unchanged. No existing test pins the old wording; `test_every_source_states_the_basis_for_its_rule` (length over 40) and `sources.py`'s own load check still pass, and `test_the_ffrh_basis_records_that_the_figures_are_cleared_for_display` pins the new one.

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest tests/test_staff_sources.py tests/test_ingest.py tests/test_storage.py -q -m "not integration"`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/ingest/staff_sources.py backend/app/ingest/promote.py backend/app/ingest/data/sources/funders.json backend/tests/test_staff_sources.py
git commit -m "feat(ingest): promote facts read from a staff dataset

A finding at a staff URL links to the dataset's private row and never creates a
public one; facts from every sheet are promoted as public rows. A finding that
cites a staff dataset without its sheet/cell marker is held with its reason.
The FFRH registry basis records that its figures are cleared for display.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: The skills

**Files:**
- Rewrite: `backend/app/ingest/skills/funder-intake-research/SKILL.md`
- Modify: `backend/app/ingest/skills/ngo-credential-research/SKILL.md`
- Modify: `docs/SKILLS.md`
- Test: `backend/tests/test_harness.py`

**Interfaces:** none. These are prose files.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_harness.py`:

```python
class TestTheIntakeSkills:
    """Spec §4 "The skill": generic, ordered, and carrying the classification rule."""

    @staticmethod
    def text(name: str) -> str:
        from app.ingest.agent import SKILLS_DIR

        return (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")

    def test_the_funder_skill_names_no_funder_and_no_file(self):
        import json
        from pathlib import Path

        text = self.text("funder-intake-research").lower()
        seeded = Path(__file__).resolve().parents[2] / "seed" / "data" / "rubrics" / "funders.json"
        names = [f["name"].lower() for f in json.loads(seeded.read_text())] if seeded.exists() else []
        assert not [n for n in names if n in text]
        for word in ("dataful", "analytics report", "ffrh", ".xlsx"):
            assert word not in text, word

    def test_it_says_where_to_look_in_order(self):
        text = self.text("funder-intake-research")
        section = text.split("## Where to look, in this order", 1)[1].split("\n## ", 1)[0]
        first, second, third = (section.index(s) for s in ("1. **Statutory", "2. **The funder's own", "3. **Recipient"))
        assert first < second < third
        assert "read_source_rows" in section and "kind = 'programme'" in section
        assert "`partner` finding" in section and "`amount`" in section
        assert "funder_csr_years" in section and "kind = 'spend'" in section

    def test_eligibility_is_one_verbatim_document(self):
        text = self.text("funder-intake-research")
        assert "verbatim" in text and "doc_type = 'funder_eligibility'" in text
        assert "one row per condition" not in text
        assert "kind='statutory_restatement'" not in text

    def test_it_carries_the_classification_rule(self):
        text = self.text("funder-intake-research")
        for word in ("**Others**", "**Environment**", "classified_by", "classification_note",
                     "classification_confirmed", "csr_sector_id", "Never pick a theme to avoid leaving one empty"):
            assert word in text, word

    def test_the_ngo_skill_names_the_staff_workbook(self):
        text = self.text("ngo-credential-research")
        assert "read_source_rows" in text and "funder sheets" in text and "`claimed`" in text
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_harness.py -q -k IntakeSkills`
Expected: 4 failures (no "Where to look" section, the old eligibility rows text, no classification rule, and no staff workbook in the NGO skill). `test_the_funder_skill_names_no_funder_and_no_file` already passes.

- [ ] **Step 3: Rewrite `funder-intake-research/SKILL.md`**

Replace the whole file with:

````markdown
---
name: funder-intake-research
description: Use when someone names one or more companies, corporate foundations, trusts or grantmakers and wants to know where their CSR money goes and what it would take to reach it. Sets the order to read sources in — statutory CSR filings under the corporate filer first (staff datasets, via read_source_rows), then the funder's own publications, then recipient-side records — and pulls ten fields per funder in intake order — route and whether it is live, receiving legal entity, grantmaker or implementer, eligibility guidelines verbatim, document checklist, hard disqualifiers, district-level geography, grant size and co-funding, live call or historical disclosure, provenance with access state; plus any open call, and the rule for classifying spend lines by domain and theme. Raw field-value-source only; no verdicts, no scoring. Not for an organisation that receives money — use ngo-credential-research. Not for one fact already in the catalog — funder_dossier answers that.
---

# What we want pulled for a funder

A researcher does the reading, under its own rules. What follows is what to put in each
researcher's task description: where to look, in which order, what to pull, and how to label
what it finds. No funder is special-cased here, and none should be.

## Where to look, in this order

The order is strength of evidence for money, not convenience.

1. **Statutory CSR filings for the corporate entity.** The filer is the company that carries the
   Section 135 obligation — often the parent company, not the foundation that runs the
   programmes.
   - Read them with `read_source_rows`, which searches every staff dataset and every sheet in each.
     Search the filer's registered name, then the foundation's.
   - Record the filer as the parent funder and the foundation as its child (`funders.parent_id`).
     Never merge the two.
   - Per fiscal year, pull the company-level figures — average net profit, prescribed CSR, amount
     spent, local-area spend, unspent — into `funder_csr_years`. A filing repeats them on every
     project line; the tool states them once per company-year. Never add them up across lines.
   - Pull each project line into `funder_activity` with `kind = 'spend'`: project, filed sector,
     state, district, outlay, amount spent, implementation mode, and the partner when one is named.
2. **The funder's own publications:**
   - the foundation's annual reports and impact reports;
   - the parent's annual report and its "Annual Report on CSR Activities" annexure;
   - the CSR policy and the annual action plan;
   - the CSR impact-assessment report;
   - the business responsibility and sustainability report.

   These give programme components and their spend, partner lists by year, district lists,
   outcomes and targets, administration and impact-assessment costs, and unspent transfers.
   Record the funder's own programme split — "₹X on programme A this year" — as
   `kind = 'programme'` rows, one per component per year, against the funder's `programs` row.
   It is the funder's own total. Never spread it across filing lines, and never add it to them:
   the two are reported side by side.
3. **Recipient-side records** — the staff CSO funder sheets, through `read_source_rows`, and
   recipients' own annual reports — for grant amounts per partner, which funders rarely publish.
   Save each as a `partner` finding for the funder: the recipient as `partner_name`, the fiscal
   year, and the `amount` as printed with its unit (`7.5`, `lakh`); promotion normalises it to
   rupees on the funder's `kind = 'partner'` line. Cite each figure by its row's marker. Where the
   recipient's own report states the same grant, cite that as well.

**Every fact names the file and sheet, or the page, it came from.** A staff-dataset row is cited
by its `[source:<document>#<sheet>:<cell>]` marker, with the dataset's `source_url` and its
registry key as `source_name`, both printed by the tool. A web fact keeps its URL.

**Amounts keep the unit they were printed in.** The tool shows rupees beside the figure as
printed; save the printed figure and its unit (`0.36`, `crore`), never the rupee figure.

## The rules that hold for all ten

**Every value carries its exact source. Including "not stated".** A URL, or a staff dataset's
marker. "Not stated" with a URL means we read the page and it was silent; "not stated" with no
URL means we did not look, and those are different answers.

**Mark every value `evidenced` or `claimed`, and never silently upgrade one to the other.**
Evidenced is a document, a number, a filing, a dated page that says it. Claimed is a bare sentence
with nothing behind it. "We fund across India" on an about-us page is claimed. A district list in
a published call is evidenced.

**Never cite an aggregator.** NGOBox, Devex, CSR trackers, LinkedIn, news coverage of a grant —
these may point you to the funder's page; they are never the source of a fact. Only the funder's
own domain, a primary document it hosts, or a staff dataset — which is the statutory filing, or
the recipient's own record, held privately.

**Pull raw.** Field, value, source, evidenced-or-claimed. One block per funder, fields in the
order below. No summary, no verdict, no comparison table, no "strong fit" — all of that is
downstream and belongs to whoever reads this.

## The ten, and the eleventh

1. **Intake route, and whether it is still live.** Portal URL, email address, or RFP process.
   Actually check it: does the portal load, is the form from 2012, does the page still exist.
   Record the check date. "No stated route" is a real and common finding — write it rather than
   inferring a route from a generic contact-us page.
2. **The exact legal entity that receives the application.** Many corporates route CSR through a
   separate foundation, and the policy names the foundation rather than the parent. Name the
   receiving body exactly.
3. **The funder's role** — grantmaker (gives money to NGOs), implementer (runs the work itself and
   solicits corporate payers, not NGO applicants), or neither (closed, or informational only). A
   "Partner with us" page can mean any of the three, so say which and quote what decided it.
4. **Eligibility guidelines, verbatim.** Look explicitly for:
   - the CSR policy's partner-selection and due-diligence clauses;
   - "partner with us", "grant guidelines", "how to apply" and FAQ pages;
   - proposal or application guidelines;
   - the annual action plan;
   - any eligibility section in an annual report.

   Pull the text **verbatim**, and keep the split this field has always made:
   - *statutory restatement* — Rule 4 of the Companies (CSR Policy) Rules copied into the policy
     (12A/80G/CSR-1, three years' track record), flagged as restatement, not as the funder's bar;
   - *the funder's own bar* — anything beyond the statutory minimum, in its own words;
   - *disqualifiers* — field 6.

   It is stored as **one eligibility guideline per funder**: a `documents` row with
   `doc_type = 'funder_eligibility'` holding the text as published, with its source URL. When the
   eligibility reaches this funder through a parent's policy — a company policy covering spend
   through its foundation — mark it `claimed` for the child and say whose document it is.
   "Not stated" still carries the URL of the page read.
5. **The document checklist, verbatim, item by item.** When one is published this is the single
   richest artefact on the page. "Lists 32 items" is the right precision; "requires various
   documents" is not. List them.
6. **Hard disqualifiers** — thresholds the funder says will get an application rejected outright:
   minimum revenue, minimum years running, minimum or maximum board size, political or religious
   bars, donor concentration limits, employee count floors. These are rejections, not credentials;
   keep them apart from field 4's restatement and own bar. They are quoted in the same eligibility
   guideline, under their own heading, because all three are conditions on the applicant.
7. **Geography at district granularity.** Districts, blocks or named work centres exactly as
   listed — state level is not an answer. If the finer list sits behind a login, say that
   explicitly rather than reporting the state.
8. **Grant size, duration and co-funding share.** Hard numbers only: a rupee ceiling, a duration in
   years, a percentage cap ("covers up to 90% of project cost"). Nothing numeric published means
   say so; never estimate from sector norms.
9. **Live call, or historical disclosure.** Many "CSR information" pages are statutory annexures
   describing money already spent last fiscal year, not an open call. Say which. A page naming an
   implementing agency as "TBD" is a live, currently-open slot — flag it.
10. **Provenance: exact source, fetch date, and access state.** Access state is its own value and it
    is load-bearing, because three of these look identical to a careless reader and only one of
    them licenses reporting an absence:
    - **readable** — 200, real text
    - **scanned** — a PDF with no text layer. The page exists and the content is unread. Never
      report an absence from one.
    - **soft-404** — HTTP 200 but boilerplate, or byte-identical to an invented URL. Treat as not
      found.
    - **archived** — read from web.archive.org because the live domain blocks or 403s. Flag it; it
      may be stale.

11. **The open call itself — only when field 9 found one.** Its title as the funder names it, the
    deadline, the grant band, and each stated requirement on its own line. It is last because the
    ten above decide whether to bother with this funder at all. Three rules, because this is the
    field most easily invented:
    - **A programme page is not a call.** "Partner with us", a themes page, a past-projects list —
      none of these is an open call, and which one it is is field 3's question. No title and no
      deadline means no call; say so rather than manufacturing one.
    - **A closed or expired call is still worth recording**, marked closed. A funder that ran a
      call last year is a funder with a door.
    - **The call's requirements are the call's, not the funder's standing bar.** These land in
      `rfps.eligibility`; field 4's land in the funder's eligibility guideline. The same sentence
      can be true in both places, and recording it twice is correct.

## Classifying a spend line: domain and theme

Every domain and theme on a line is an **inference**. Record it as one.

- **Classify each line by its project name and named partner**, not by the Schedule VII sector it
  was filed under. Filings misfile often: financial-inclusion work filed under education or
  health, a grant to an NGO filed under a central government fund.
- **A domain, always** — one of the five:
  - **Others**: relief, sports, administration, unlabelled lines, and lines that list several
    sectors at once.
  - **Environment**: environmental sustainability, conservation and animal welfare that is not a
    livelihood programme.
  - otherwise, the programme domain the project and partner point to.
- **A theme, only as far as the evidence goes:**
  - a sub-theme when the project or the partner points to one;
  - a theme when only the broad area is clear;
  - none otherwise — "Sustainable Livelihood" or "Education" alone supports no theme.

  Never pick a theme to avoid leaving one empty. Environment and Others have no themes.
- **Record what it rests on:**
  - `classified_by` — `filed_sector` (only where the filed sector is unambiguous), `project_name`,
    `partner` (what the named organisation is known for), or `report` (the funder's own programme
    naming);
  - a one-line `classification_note` quoting the evidence, e.g.
    `project 'Financial Literacy & Inclusion'; filed under Education`.

  Leave `classification_confirmed` false; a person sets it when they vet the line.
- **The filed sector is stored as filed**, in `csr_sector_id`, whatever the classification says.
- **A `programme` row is classified the same way**, with `classified_by = 'report'` when the
  funder's own programme naming is the evidence.

## The CSO side

The staff CSO workbook also serves research on an organisation that receives money;
`ngo-credential-research` names it as a source. A recipient-side figure cites the recipient's own
document, or the staff dataset's marker for the sheet and cell it came from.

## When a source will not open

Try the Internet Archive snapshot of the same URL before giving up, and label the result
`archived`. If a primary legal source (mca.gov.in, csr.gov.in, indiacode.nic.in) is unreachable,
say so, and say that any statutory claim is corroborated from professional commentary instead of
read directly. That is weaker evidence, and it is labelled as such, not presented as equivalent.

## What this skill does not do

It does not decide fit, score a funder, rank a list or lay out a comparison. It does not write to
the catalog. It produces ten cited fields per funder, the classified lines, and any open call it
found, and stops.
````

- [ ] **Step 4: Add the staff workbook to `ngo-credential-research/SKILL.md`**

(a) Replace the line `**Never cite an aggregator.** Only the organisation's own domain, or a primary document it has published.` with:

```markdown
**Never cite an aggregator.** Only the organisation's own domain, a primary document it has
published, or the staff CSO workbook below.
```

(b) Insert before `## FCRA is not part of this chain`:

```markdown
## A staff source: the CSO workbook

Sangam holds an internal workbook on partner CSOs, uploaded by staff under partner permission: a
profile sheet (registration, programmes, geography, leadership) and two funder sheets. Read it
before the web, with `read_source_rows` and the organisation's name.

- **Cite the sheet.** Each row carries a `[source:<document>#<sheet>:<cell>]` marker. A finding
  from it uses the dataset's `source_url` and registry key, both printed by the tool.
- **It is the organisation's self-reported record.** Every value from the profile sheet is
  `claimed`. A legal status or registration number written there is a lead to the certificate, not
  the certificate; field 1 still needs the number or the certificate itself.
- **The funder sheets give its funders by year, with amounts.** Cite each by its marker. They
  are the organisation's own account of who funds it, so a funder named only there is `claimed`
  until the funder's or the organisation's published document confirms it. A grant amount is
  saved on the funder's side, as a `partner` finding with the `amount` as printed and its unit;
  promotion stores it in rupees on that funder's `kind = 'partner'` line.
- Contact details are not in what the tool returns, by design.
```

- [ ] **Step 5: Note it in `docs/SKILLS.md`**

After the paragraph ending `…that exists on no funder table and decides whether a funder may give at all.`, add:

```markdown
Both "what to pull" skills name `read_source_rows`, the researcher's reader for the staff
datasets. That is detail added to a tool the prompts already name. `instructions.md` and the
researcher's own prompt both carry it, so `test_a_tool_is_never_reachable_only_through_a_skill`
still holds. Neither skill names a funder or a file: what to read, in which order, and how to
label it is the procedure, and the procedure is generic.
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest tests/test_harness.py -q`
Expected: all pass, including `test_every_skill_is_one_directory_deep_with_matching_frontmatter` (the description is 971 characters and starts with "Use when").

- [ ] **Step 7: Commit**

```bash
git add backend/app/ingest/skills/funder-intake-research/SKILL.md backend/app/ingest/skills/ngo-credential-research/SKILL.md docs/SKILLS.md backend/tests/test_harness.py
git commit -m "docs(skills): where to look, eligibility verbatim, classification as inference

The intake skill reads statutory filings under the corporate filer first, records
the funder's own programme split as programme rows, keeps eligibility as one
verbatim document, and classifies every spend line with its basis. Generic: no
funder, file or company named. The NGO skill reads the staff CSO workbook.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Confidentiality guard, full verification, upload and acceptance run

**Files:**
- Modify: `.gitignore`
- Test: `backend/tests/test_source_layouts.py`

**Interfaces:** none.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_source_layouts.py`:

```python
def test_no_spreadsheet_is_tracked():
    """The staff datasets are confidential. Fixtures are generated in code; a real file in the
    repo, under any name, is the leak this exists to catch."""
    import subprocess

    root = BACKEND.parent
    tracked = subprocess.run(["git", "ls-files", "*.xlsx", "*.xls", "*.xlsm", "*.jsonl.gz"],
                             cwd=root, capture_output=True, text=True, check=True).stdout.split()
    assert tracked == []


def test_gitignore_keeps_spreadsheets_out():
    assert "*.xlsx" in (BACKEND.parent / ".gitignore").read_text()
```

- [ ] **Step 2: Run the tests and confirm one fails**

Run: `cd backend && pytest tests/test_source_layouts.py -q -k "tracked or gitignore"`
Expected: `test_gitignore_keeps_spreadsheets_out` fails, and `test_no_spreadsheet_is_tracked` passes.

- [ ] **Step 3: Ignore spreadsheets**

Append to `.gitignore`:

```gitignore

# Staff datasets are confidential and live only in the private staff-sources bucket.
# Tests generate their workbooks in code (backend/tests/staff_source_fixtures.py).
*.xlsx
*.xls
*.xlsm
*.rows.jsonl.gz
```

- [ ] **Step 4: Run the full suite and lint**

```bash
cd backend && ruff check . && pytest -q -m "not integration"
cd backend && pytest -q -m integration        # needs make up && make migrate, with (b) merged
cd frontend && npm run lint && npm run build
SMOKE_SKIP_LLM=1 make smoke
```

Expected:
- ruff is clean;
- every unit test passes;
- integration passes, including the six RLS cases and `TestAStaffDatasetIsStaffOnly`;
- `next build` succeeds;
- smoke prints all OK.

- [ ] **Step 5: Commit**

```bash
git add .gitignore backend/tests/test_source_layouts.py
git commit -m "chore: keep spreadsheets out of the repo

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Upload the three files to staging (staff, by hand, after merge)**

Back up first, per CLAUDE.md (`make db-backup ENV=staging` or the Supabase dashboard). Then run:

```bash
make migrate ENV=staging
make staff-source ENV=staging KEY=mca_csr SPLIT=1 FILE="$HOME/Downloads/<analytics report>.xlsx"
make staff-source ENV=staging KEY=mca_csr FILE="$HOME/Downloads/<dataful subset>.xlsx"
make staff-source ENV=staging KEY=ffrh_funder_datasets FILE="$HOME/Downloads/<CSO workbook>.xlsx"
```

Expected:
- the analytics report prints one `added: document N · staff-sources/<sha12>-mca_csr_analytics_report--<year>.xlsx · <rows> rows` line per year sheet, eleven in all;
- each of the other two prints one line.

Then check in `psql`:

```sql
SELECT id, source_name, as_of, content_md IS NULL AS empty, is_public, org_id FROM documents
WHERE doc_type = 'source_dataset' ORDER BY id;
```

Expected: 13 rows, every row with `empty = t`, `is_public = f` and `org_id` NULL. Do not paste row counts or anything else from these files into the PR.

- [ ] **Step 7: Acceptance run (spec §5), on staging, in the Import chat as a staff user**

Pick one corporate funder present in both MCA datasets. Ask Import to research it and push it. Then check:

1. **Totals.** `SELECT fiscal_year, sum(amount) FROM funder_activity WHERE funder_id = <parent> AND kind = 'spend' GROUP BY 1` equals, for each year, the `CSR spent` on the tool's company-year line for that year. A filing whose project lines do not add up to its total is a finding to report, not a reason to edit the lines.
2. **Domains.** `SELECT count(*) FROM funder_activity WHERE funder_id = <parent> AND kind = 'spend' AND (domain_tag_id IS NULL OR classified_by IS NULL)` returns 0.
3. **Themes.** `SELECT count(*) … WHERE theme_tag_id IS NOT NULL AND (classification_note IS NULL OR classification_note = '')` returns 0.
4. **Programme rows.** Any `kind = 'programme'` rows appear in `funder_dossier` beside the filing totals and are not included in check 1's sum.
5. **Others.** Lines whose project is relief, sports, administration, unlabelled or multi-sector carry `domain-others`.
6. **Partner amounts.** For a funder named in the CSO funder sheets, `SELECT count(*) FROM funder_activity WHERE funder_id = <funder> AND kind = 'partner' AND amount IS NOT NULL` is at least the number of sheet rows for that funder with a stated amount and an exact fiscal year, and each `amount` equals the rupee figure the tool printed beside the sheet's value (lakh and crore applied once). Rows giving a period, not one fiscal year, are reported, not written.
7. **Markers and public rows.** `promote`'s report lists under `held` any finding that cited a staff dataset without its marker. `SELECT count(*) FROM funder_activity a JOIN documents d ON d.id = a.document_id WHERE d.doc_type = 'source_dataset' AND NOT a.is_public` returns 0: facts promoted from the staff datasets are public rows (D14), while `SELECT is_public FROM documents WHERE doc_type = 'source_dataset'` is false on every row.

Record pass/fail per check in the PR. Use counts only — no names or figures.

- [ ] **Step 8: PR description must say**

- **Staff-only enforcement.** #92 is merged. The `documents` row is staff-only through `documents_read` RLS and `readable_document`. The download route also refuses to sign a staff object on a public or org row. Import is `require_staff`. `read_source_rows` runs as the owner, like every agent tool until 0027's "step 8", so the Import route is its gate. The bucket's `storage.objects` policy is staff SELECT only, and it fails closed where the migration role may not add it.
- **Where data goes.** Tool output, rows included, reaches the model provider, the LangGraph checkpoint tables (owner-only, not catalogued) and, when tracing is on, Langfuse, like any tool output. Nothing is logged by the app.
- **Spec refinements:**
  - a citation is a cell, not a row;
  - amount units include `inr`, with per-cell suffixes;
  - the sidecar;
  - `--split-sheets`;
  - the `.invalid` source URL;
  - a staff-dataset finding without its sheet/cell marker is held;
  - facts from every sheet, the CSO funder sheets included, are promoted as public rows (D14), and the `ffrh_funder_datasets` basis says FFRH has cleared them for display;
  - the tool sits on the researcher, not the supervisor.
- **Migration.** The number (0032) follows (b) and is reassigned at merge if needed.

---

## Self-Review

| Requirement (spec) | Task |
|---|---|
| D8: a private `staff-sources` bucket, guarded like 0020 (no-op without `storage`) | 6 |
| D8: `storage.split()` learns the bucket | 6 |
| D8: readable by staff only, never org admins. `readable_document()`, `documents_read` RLS, `storage.objects` policy limited to `app.is_staff()`, and the enforcement state stated | 6, 7, 12 (PR text) |
| §4: each file gets a `documents` row: `source_dataset`, `is_public = false`, org and funder NULL, `source_name` = registry key, `storage_path = 'staff-sources/<sha12>-<name>'`, no `content_md`, no chunks | 7, 8 |
| §4: `scripts/upload_staff_source.py`, a one-off staff script using the service key | 8 |
| D13: a layout profile per file, with `source_key`, `filename_pattern`, per-sheet layout (`table`, `blocks_by_column`, `sections_by_heading`), header row, block/section detection, `column_map` by position where names repeat, normalised fields, `amount_unit` | 2, 3, 4, 5 |
| D13: a sheet without a profile entry is an error (at read and at upload) | 3, 8 |
| D13: every sheet of every file is read and returns normalised rows in rupees | 3, 4, 5, 7 |
| §4 tool: `read_source_rows(match, source_keys=None, fiscal_years=None, limit=500)` in `pipeline_tools.py` | 9 |
| §4 tool: matches `match` or the funder's aliases; rupees with the raw value and unit; cited `[source:<document_id>#<sheet>:<row>]`; never raises | 7, 9 |
| §4 tool: registered in the Import agent, named in instructions, labelled in `toolLabels.ts` | 9 |
| §4: `openpyxl` in runtime dependencies (`pyproject` and `uv.lock`, image verified) | 1 |
| §4: `DISPATCHABLE` unchanged | Global Constraints (no task touches `sources.py` or the registry) |
| D9: skill generic, no funder, file or company named (tested) | 11 |
| §4 skill: "Where to look, in this order". Filings under the corporate parent via `read_source_rows`, parent/child, `funder_csr_years`, `kind='spend'`; own publications (list); recipient-side records | 11 |
| D12: the programme split as `kind='programme'` rows, never spread onto filing lines | 11 (skill); acceptance check 4 in 12 |
| §4 skill: every fact names the file and sheet, or the page | 11; marker in 7 |
| §4 skill: eligibility guideline search list, verbatim, three-way split, one `funder_eligibility` document, `claimed` via a parent's policy, "not stated" with URL | 11 |
| D11: classification rule. By project and partner, a domain always (Others, Environment), theme at the most specific level or none, `classified_by`, a note, confirmed false, filed sector kept in `csr_sector_id` | 11; acceptance checks 2, 3, 5 in 12 |
| §4 CSO side: `ngo-credential-research` names the staff sheets; read via `read_source_rows`, cite the sheet, treat as self-reported | 11 |
| §4 kept: provenance, evidenced/claimed, never an aggregator; recipient figures cite the recipient's document or the sheet's document id | 11 |
| §5: layout unit tests on synthetic fixtures: repeated column names, side-by-side blocks, headed sections, lakh vs crore, a sheet without a profile fails | 2, 3, 4, 5 |
| §5: real files never committed | 12 (`test_no_spreadsheet_is_tracked`, `.gitignore`) |
| §5: the acceptance run: totals per FY, domain and `classified_by` on every line, themes only with a note, programme rows beside not summed, Others | 12 (Step 7), made possible by 10 |
| §5: `make smoke`, unit and integration tests | 12 |
| §4 recipient-side records give grant amounts per partner: saved on `partner` findings, written in rupees to `funder_activity` `kind = 'partner'` | 9 (prompt, tool docstring), 11 (skills and test), 12 (acceptance check 6); the column wiring is plan (b) Task 11 |
| D14: every sheet citable and promotable; facts promoted from them public under the default `is_public`; the files stay staff-only; the `ffrh_funder_datasets` basis updated | 7 (no sheet withheld), 9 (prompt), 10 (`hold_unmarked`, basis), 11 (skills), 12 (acceptance check 7) |

### Ambiguities resolved

1. **#92 is merged**, contrary to the spec's and the brief's premise. The plan states the enforcement that is actually live, and ships the `storage.objects` policy now.
2. **Some layout facts were not in the spec.** The analytics workbook is 59 MB, which is over the 50 MB bucket and download limit, and a full parse takes about 70 s. Three resolutions follow:
   - **upload-time normalised sidecars**, keyed by profile digest, with fallback to the workbook;
   - **`--split-sheets`** for table-layout files over the limit;
   - **a citation is `<sheet>:<cell>`**, because side-by-side blocks share row numbers.
3. **Amount units add `inr`**, with per-cell `lakh`/`cr` suffixes overriding the sheet unit. The blocks sheet is headed ₹ but mixes units.
4. **Normalised fields go beyond the spec's twelve.** Added: `company_state`, four company-level figures, `funder_type`, `partner`, `role`, `detail` and `omit`. Company-level figures are rendered once per company-year.
5. **Year handling.** Only an exact `YYYY-YY` becomes a fiscal year. Ranges and "(Ongoing)" stay as a period; the year filter excludes them and says how many.
6. **Implementation mode.** "Set up by Central or State Government" maps to `implementing_agency`.
7. **The tool lives on `entity-researcher`, not the supervisor**, which researches nothing. Instructions name it in the not-yours table.
8. **Findings need an http(s) `source_url`.** Each dataset gets a non-resolving `https://staff-sources.sangam.invalid/<sha12>`. Promotion links it to the private row and never creates a public one.
9. **Every sheet is citable and promotable (D14).** FFRH has cleared the CSO workbook's figures for display, so facts from its funder sheets are promoted as public rows like the filings', and the registry's `basis` now says so. The profiles carry no per-sheet display flag. The raw files stay in the staff-only bucket. What promotion still holds is a staff-dataset finding without its `[source:…]` marker, which could not be traced to its sheet and cell.
10. **Neutral names.** Stored keys and titles carry the profile name, never the original file name, because Ask's SQL catalog shows `documents.title` and `storage_path`. `Contact & Address` is declared `omit`.
11. **The upload script runs on the host venv,** because the image mounts only `app/`, `seed/` and `db/`. It runs via `make staff-source`, which honours `ENV`.
````
12. **Where a recipient-side amount lands.** `grants` has no writer, so a grant amount from a CSO funder sheet is saved as a `partner` finding with its `amount`, and plan (b) Task 11 writes it to `funder_activity.amount` on the `kind = 'partner'` line, in rupees, as a public row. The finding keeps the figure as printed with its unit; `Money.inr` is the one conversion.
