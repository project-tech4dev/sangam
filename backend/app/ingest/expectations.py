"""What the database expects, per research concept, derived from the SQL catalog.

The catalog is already the schema as data — 40 tables with their columns, the
CHECK-constraint value lists and the gotchas — and `verify_against_db()` raises
at boot when it drifts from the live schema. So a researcher's targets are
derived from it rather than written down a second time and left to rot.

What comes out is the list of fields a person could actually find in a public
source: no surrogate keys, no provenance (the tool fills that in), and no
foreign keys except the few a source states by name — a district, a state, a
parent programme — which the writer resolves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.agent.tools.sql.catalog import CATALOG

# A concept is a research finding; a table is where it lands. 'identity' is the
# entity itself, which is why it maps to funders rather than to a fact table.
CONCEPT_TABLES: dict[str, str] = {
    "identity": "funders",
    "identifier": "funder_identifiers",
    "csr_year": "funder_csr_years",
    "csr_spend": "funder_csr_spend",
    "footprint": "funder_footprints",
    "stated_geography": "funder_locations",
    "partner": "funder_partners",
    "program": "programs",
    "grant": "grants",
    "metric": "metrics",
    "contact": "contacts",
    "document": "documents",
    "rfp": "rfps",
}

# Filled in by the tool from the finding's own evidence, never researched as a field.
PROVENANCE = frozenset({
    "source_url", "source_name", "fetched_at", "as_of", "document_id",
    "archive_url", "content_hash", "extractor_version",
})

# Foreign keys a source does state, in words. The writer resolves each name to
# an id; the researcher only ever reports what the report printed.
# A single location_id is deliberately absent: a table with one place column
# still needs both halves from the researcher, because "Barpeta" alone cannot
# be resolved and "Barpeta, Assam" can. It is added as a pair in EXTRA.
NAMED_AS: dict[str, str] = {
    "state_location_id": "state",
    "district_location_id": "district",
    "program_id": "program_name",
    "parent_id": "parent_name",
}

# Ours, not the source's: slugs and registry status are assigned here, and the
# jsonb catch-alls are where a fact goes when it has no column, not a target.
INTERNAL = frozenset({
    "slug", "registry_status", "cohort", "is_current", "verified", "is_public",
    "created_at", "uploaded_by", "is_ai_generated", "storage_path", "content_md",
    "profile", "sections", "contact", "details", "outcomes", "valid_from", "valid_to",
})


# Columns that are a research target on most tables but ours on one. A
# document's status is our reading workflow, not something a source states;
# a grant's and a programme's status are facts about the world.
OURS: dict[str, frozenset[str]] = {
    "document": frozenset({"status"}),
    # `details` is our own catch-all, not something a call publishes.
    "rfp": frozenset({"details"}),
}


@dataclass(frozen=True, slots=True)
class Expected:
    name: str
    type: str
    note: str
    values: tuple[str, ...]
    required: bool

    def describe(self) -> str:
        bits = [f"{self.name} ({self.type})"]
        if self.required:
            bits.append("REQUIRED")
        if self.values:
            bits.append("one of: " + ", ".join(self.values))
        if self.note:
            bits.append(self.note)
        return " — ".join(bits)


# What a researcher must state for the row to be writable: NOT NULL, and with
# nobody else to supply it. A NOT NULL column that carries a DDL default is not
# here — programs.kind defaults to 'programme' and contacts.kind to 'other' —
# and neither is grants.status, which has no default but whose 'unconfirmed'
# value exists precisely so the writer can say "the source did not say".
# Demanding those would make the model guess, which is the failure this file
# exists to prevent.
REQUIRED: dict[str, frozenset[str]] = {
    "identity": frozenset({"name"}),
    "identifier": frozenset({"id_type", "id_value"}),
    "csr_year": frozenset({"fiscal_year"}),
    "csr_spend": frozenset({"fiscal_year", "amount"}),
    "footprint": frozenset({"fiscal_year", "state"}),
    "stated_geography": frozenset({"state"}),
    "partner": frozenset({"fiscal_year", "partner_name"}),
    "program": frozenset({"name"}),
    "grant": frozenset({"title", "recipient_name"}),
    "metric": frozenset({"name"}),
    "contact": frozenset({"name"}),
    "document": frozenset({"title", "doc_type"}),
    "rfp": frozenset({"title"}),
}


# Facts worth researching that have no column of their own yet. Surfacing them
# here is what stops "we never asked" from looking like "the source never said".
_STATE = Expected(
    name="state",
    type="text",
    note="the state as the source names it",
    values=(),
    required=True,
)
_DISTRICT = Expected(
    name="district",
    type="text",
    note="the district, when the source is that precise. Never invent one from a city or a "
         "programme name",
    values=(),
    required=False,
)

EXTRA: dict[str, tuple[Expected, ...]] = {
    "footprint": (_STATE, _DISTRICT),
    "stated_geography": (_STATE, _DISTRICT),
    "metric": (
        Expected(name="state", type="text", note="the state, when the figure is for one place",
                 values=(), required=False),
        _DISTRICT,
    ),
    "grant": (
        Expected(
            name="recipient_name",
            type="text",
            note="the organisation that received the money, as printed. grants.org_id is NOT "
                 "NULL, so a recipient not in orgs belongs in funder_partners instead",
            values=(),
            required=True,
        ),
    ),
    "document": (
        Expected(
            name="as_of",
            type="text",
            note="the period the document describes, e.g. 'FY2023-24'. NOT when you read it — "
                 "fetched_at is that, and the two are different",
            values=(),
            required=False,
        ),
    ),
    # contacts.email exists in the schema but is deliberately absent from the
    # SQL catalog, so the derivation cannot see it. Asked for explicitly, under
    # the rule that only a shared mailbox is ever recorded.
    "contact": (
        Expected(
            name="email",
            type="text",
            note="a SHARED mailbox only (csr@, grants@, csrhelpdesk@) — never an individual's",
            values=(),
            required=False,
        ),
        Expected(
            name="is_role_mailbox",
            type="boolean",
            note="attest that the address belongs to the organisation, not to a person",
            values=(),
            required=False,
        ),
    ),
    "rfp": (
        # heavy in the catalog (jsonb), so the derivation drops it — but a
        # call's eligibility rules are the single thing a fundraiser reads it
        # for, so it is asked for explicitly.
        Expected(
            name="eligibility",
            type="text[]",
            note="each stated requirement on its own line, e.g. '3 years of audited accounts'",
            values=(),
            required=False,
        ),
        Expected(
            name="state",
            type="text",
            note="when the call is limited to one state",
            values=(),
            required=False,
        ),
        _DISTRICT,
        Expected(
            name="sector",
            type="text",
            note="the theme the call is for, as printed",
            values=(),
            required=False,
        ),
    ),
    "csr_spend": (
        Expected(
            name="sector",
            type="text",
            note=(
                "the funder's own words for the theme. Kept in notes: tags.kind allows "
                "'csr_sector' but no Schedule VII taxonomy is seeded to normalise against"
            ),
            values=(),
            required=False,
        ),
    ),
}


def expected_fields(concept: str) -> tuple[Expected, ...]:
    """The fields a researcher can fill for one concept, in column order."""
    table = CATALOG[CONCEPT_TABLES[concept]]
    required = REQUIRED.get(concept, frozenset())
    out: list[Expected] = []
    for column in table.columns:
        name = column.name
        if name == "id" or name in PROVENANCE or name in INTERNAL or column.heavy:
            continue
        if name in OURS.get(concept, frozenset()):
            continue
        if name.endswith("_id"):
            if name not in NAMED_AS:
                continue
            name = NAMED_AS[name]
        out.append(
            Expected(
                name=name,
                type="text" if name in NAMED_AS.values() else column.type,
                note=column.note,
                values=column.values,
                required=name in required,
            )
        )
    return tuple(out) + EXTRA.get(concept, ())


def concepts_for(entity_kind: str) -> tuple[str, ...]:
    """Which concepts are worth chasing for this kind of entity.

    Every table above hangs off funders. An NGO's facts have no writer yet, so
    researching one is still worth doing and still lands in entity_research —
    it just does not become a catalog row. See docs/INGEST.md.
    """
    if entity_kind == "org":
        return ("identity", "identifier", "program", "metric", "contact", "document")
    return tuple(CONCEPT_TABLES)


def recent_fiscal_years(today: date | None = None, count: int = 3) -> tuple[str, ...]:
    """The last `count` fiscal years a funder could have reported on.

    An Indian FY runs April to March, and the CSR annexure for one is published
    months after it closes — so the newest year worth asking for is the one that
    has already ended, not the one we are in.
    """
    today = today or datetime.now(UTC).date()
    ended = today.year - 1 if today.month >= 4 else today.year - 2
    return tuple(f"FY{y}-{str(y + 1)[2:]}" for y in range(ended, ended - count, -1))
