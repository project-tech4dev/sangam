"""What the database expects, per research concept, derived from the SQL catalog.

The catalog is already the schema as data — its tables with their columns, the
CHECK-constraint value lists and the gotchas — and `verify_against_db()` raises
at boot when it drifts from the live schema. So a researcher's targets are
derived from it rather than written down a second time and left to rot.

What comes out is the list of fields a person could actually find in a public
source: no surrogate keys, no provenance (the tool fills that in), and no
foreign keys except the few a source states by name — a district, a state, a
parent programme — which the writer resolves.

It is also the concept registry. The vocabulary used to be written out seven
times across four modules, and the one list with no test under it — the brief's
section titles — was missing `rfp`, so every RFP finding ever saved was dropped
from every brief with no error anywhere. `CONCEPTS` is now the single record and
the rest are derived views that keep their old names, so the invariant tests
still read as invariants. `FINDING_MODELS` is the one that cannot derive:
research_records.py imports this module, so this module cannot import it back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from app.agent.tools.sql.catalog import CATALOG

# Which kind of entity offers a concept. programs, metrics, contacts and documents each carry both an
# org_id and a funder_id, so they are the same concept either way and only the foreign key changes.
# Everything else hangs off one or the other: an NGO's 12A, 80G and FCRA live in org_identifiers, and
# a funder keeps only a CIN, on its own row.
_BOTH = frozenset({"funder", "org"})
_FUNDER = frozenset({"funder"})
_ORG = frozenset({"org"})

@dataclass(frozen=True, slots=True)
class ConceptSpec:
    """One research concept: where it lands, what it is called, who offers it."""

    table: str
    title: str
    kinds: frozenset[str] = _FUNDER
    promotable: bool = True
    # Researched deliberately and deliberately not stored as its own column.
    # Each entry is a decision; an undocumented gap is a bug.
    not_written: dict[str, str] = field(default_factory=dict)
    # For a concept sharing its table: the rows it owns, e.g. ("kind", "spend"), and the columns it
    # may fill. None means the whole table; expected_fields, research_goals and the writers all read it.
    row_filter: tuple[str, str] | None = None
    columns: tuple[str, ...] | None = None


def activity_kind(concept: str) -> str:
    """The funder_activity.kind a concept owns, from its row_filter; the writers key on it."""
    column, value = CONCEPTS[concept].row_filter or (None, None)
    if column != "kind" or value is None:
        raise KeyError(f"{concept!r} owns no funder_activity kind")
    return value


# A concept is a research finding; a table is where it lands. 'identity' is the
# entity itself, which is why it maps to funders rather than to a fact table.
# 'stated_geography' is where a funder SAYS it prioritises and 'footprint' is
# where money demonstrably went: two concepts and two tables, never one.
CONCEPTS: dict[str, ConceptSpec] = {
    "identity": ConceptSpec("funders", "Identity"),
    "csr_year": ConceptSpec("funder_csr_years", "CSR position by year"),
    "csr_spend": ConceptSpec(
        "funder_activity",
        "Project and sector spend",
        row_filter=("kind", "spend"),
        columns=("fiscal_year", "program_id", "domain_tag_id", "theme_tag_id", "classified_by",
                 "classification_note", "state_location_id", "project_name", "designation",
                 "implementation_mode", "partner_name", "partner_csr1", "outlay", "amount",
                 "project_count", "is_ongoing", "notes"),
        not_written={
            "sector": "resolved to funder_activity.csr_sector_id when it names a Schedule VII clause, "
                      "and kept in notes in the funder's own words either way",
        },
    ),
    "footprint": ConceptSpec(
        "funder_activity", "Where the work ran", row_filter=("kind", "footprint"),
        columns=("fiscal_year", "program_id", "state_location_id", "name_as_printed", "notes"),
    ),
    "stated_geography": ConceptSpec("funder_locations", "Where it says it prioritises"),
    # A named partner in a year and, since 0034, a grant: its amount, dates and status, and partner_org_id
    # when the organisation is catalogued.
    "partner": ConceptSpec(
        "funder_activity", "Partners and grants", row_filter=("kind", "partner"),
        columns=("fiscal_year", "program_id", "project_name", "partner_name", "partner_canonical",
                 "partner_csr1", "partner_kind", "outlay", "amount", "start_date", "end_date",
                 "relationship_status", "notes"),
    ),
    # D12: the funder's OWN figure per programme component. Never summed with spend lines and never
    # spread onto them; the two are reported side by side.
    "programme_spend": ConceptSpec(
        "funder_activity", "The funder's own programme split", row_filter=("kind", "programme"),
        columns=("fiscal_year", "program_id", "domain_tag_id", "theme_tag_id", "classified_by",
                 "classification_note", "amount", "notes"),
    ),
    # The funder's standing eligibility (D3): one documents row per page, the text verbatim, keeping
    # the split funder-intake-research field 4 makes. NOT rfps.eligibility, which is one call's.
    "eligibility_guideline": ConceptSpec(
        "documents", "Eligibility guidelines",
        row_filter=("doc_type", "funder_eligibility"), columns=("title",),
    ),
    "program": ConceptSpec("programs", "Programmes", kinds=_BOTH),
    "metric": ConceptSpec("metrics", "Reach and outcomes", kinds=_BOTH),
    "contact": ConceptSpec("contacts", "Contacts", kinds=_BOTH),
    "document": ConceptSpec(
        "documents",
        "Source documents",
        kinds=_BOTH,
        not_written={
            "title": "written by ensure_document, which takes a shim rather than a record",
            "doc_type": "written by ensure_document",
            "as_of": "written by ensure_document",
        },
    ),
    "rfp": ConceptSpec("rfps", "Open calls for proposals"),
    # The org side. Namespaced because Finding is a tagged union on `concept`
    # and two members cannot both declare Literal["identity"]. org_tags is
    # deliberately absent: tag_id is a bare _id, so the concept would have no
    # field naming its own subject.
    "org_identity": ConceptSpec("orgs", "Identity", kinds=_ORG),
    "org_identifier": ConceptSpec(
        "org_identifiers",
        "Registrations and their status",
        kinds=_ORG,
        # valid_from is INTERNAL elsewhere (a place link's bookkeeping); here a certificate states it.
        # checked_at, checked_by and evidence_document_id belong to a staff member's manual check.
        columns=("id_type", "id_value", "status", "valid_from", "valid_until", "check_method",
                 "application_ref", "notes"),
    ),
    "org_financials": ConceptSpec("org_financials", "Income and spending by year", kinds=_ORG),
    "org_location": ConceptSpec("org_locations", "Where it works", kinds=_ORG),
}

# Derived views. They keep the names the four modules already import, so the
# invariant tests over them still read as invariants — they just cannot fail
# through a missed edit any more.
CONCEPT_TABLES: dict[str, str] = {n: c.table for n, c in CONCEPTS.items()}
CONCEPT_TITLES: dict[str, str] = {n: c.title for n, c in CONCEPTS.items()}
PROMOTABLE: tuple[str, ...] = tuple(n for n, c in CONCEPTS.items() if c.promotable)
NOT_WRITTEN: dict[str, dict[str, str]] = {
    n: c.not_written for n, c in CONCEPTS.items() if c.not_written
}

# Filled in by the tool from the finding's own evidence, never researched as a field.
PROVENANCE = frozenset({
    "source_url", "source_name", "fetched_at", "as_of", "document_id",
    "archive_url", "content_hash", "extractor_version",
})

# The evidence tier: filled from a finding's own source and tier, never a target (`evidence` on a finding
# is the quoted sentence).
TIER = frozenset({"source_type", "evidence"})

# doc_type values written only by their own path: the eligibility concept, the template path and the
# staff-source upload. A `document` finding may not use them, and ensure_document keys them apart.
RESERVED_DOC_TYPES = frozenset({"funder_eligibility", "proposal_template", "source_dataset"})

# Foreign keys a source does state, in words. The writer resolves each name to
# an id; the researcher only ever reports what the report printed.
# A single location_id is deliberately absent: a table with one place column
# still needs both halves from the researcher, because "Barpeta" alone cannot
# be resolved and "Barpeta, Assam" can. It is added as a pair in EXTRA.
NAMED_AS: dict[str, str] = {
    "state_location_id": "state",
    "program_id": "program_name",
    "domain_tag_id": "domain",
    "theme_tag_id": "theme",
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
# a partner line's and a programme's status are facts about the world.
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
# and neither is a partner line's relationship_status, which is NULL when no source said.
# Demanding those would make the model guess, which is the failure this file
# exists to prevent.
REQUIRED: dict[str, frozenset[str]] = {
    "identity": frozenset({"name"}),
    "csr_year": frozenset({"fiscal_year"}),
    "csr_spend": frozenset({"fiscal_year", "amount", "domain", "classified_by"}),
    "footprint": frozenset({"fiscal_year", "state"}),
    "stated_geography": frozenset({"state"}),
    "partner": frozenset({"fiscal_year", "partner_name"}),
    "programme_spend": frozenset({"fiscal_year", "program_name", "amount", "domain", "classified_by"}),
    "eligibility_guideline": frozenset({"title"}),
    "program": frozenset({"name"}),
    "metric": frozenset({"name"}),
    "contact": frozenset({"name"}),
    "document": frozenset({"title", "doc_type"}),
    "rfp": frozenset({"title"}),
    "org_identity": frozenset({"name"}),
    "org_identifier": frozenset({"id_type", "status"}),
    "org_financials": frozenset({"fiscal_year"}),
    # org_locations.role is NOT NULL but defaults to 'operates', so it is not
    # demanded. `state` is, for the same reason stated_geography demands it.
    "org_location": frozenset({"state"}),
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
    "footprint": (_DISTRICT,),
    "stated_geography": (_STATE, _DISTRICT),
    # org_locations has one location_id and no NAMED_AS entry, so the
    # derivation drops it entirely — the pair is how a place gets stated.
    # orgs.registered_location_id is dropped the same way and deliberately not
    # added back: a registered address is this concept with role='registered',
    # not a second field on org_identity.
    "org_location": (_STATE, _DISTRICT),
    "metric": (
        Expected(name="state", type="text", note="the state, when the figure is for one place",
                 values=(), required=False),
        _DISTRICT,
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
    "eligibility_guideline": (
        Expected(name="as_of", type="text", note="the period or version the guideline describes",
                 values=(), required=False),
        Expected(name="statutory_restatement", type="text",
                 note="Rule 4 of the CSR Rules copied into the policy, VERBATIM. Not the funder's own bar",
                 values=(), required=False),
        Expected(name="own_bar", type="text",
                 note="anything beyond the statutory minimum, in the funder's own words, verbatim",
                 values=(), required=False),
        Expected(name="disqualifiers", type="text",
                 note="stated grounds for outright rejection, verbatim", values=(), required=False),
        Expected(name="not_stated", type="boolean",
                 note="the page was read and states no eligibility; source_url is still that page",
                 values=(), required=False),
    ),
    "csr_spend": (
        _DISTRICT,
        Expected(
            name="sector",
            type="text",
            note="the Schedule VII sector the line was FILED under, as printed; stored in csr_sector_id "
                 "when it names a clause",
            values=(),
            required=False,
        ),
    ),
}


def expected_fields(concept: str) -> tuple[Expected, ...]:
    """The fields a researcher can fill for one concept, in column order."""
    spec = CONCEPTS[concept]
    table = CATALOG[spec.table]
    required = REQUIRED.get(concept, frozenset())
    out: list[Expected] = []
    for column in table.columns:
        name = column.name
        if spec.columns is not None and name not in spec.columns:
            continue
        if name == "id" or name in PROVENANCE or name in TIER or column.heavy:
            continue
        if name in INTERNAL and not (spec.columns is not None and name in spec.columns):
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

    Both kinds now promote: the shared concepts write the same table through a
    different foreign key, and each kind's own concepts write its own tables.
    """
    return tuple(n for n, c in CONCEPTS.items() if entity_kind in c.kinds)


def recent_fiscal_years(today: date | None = None, count: int = 3) -> tuple[str, ...]:
    """The last `count` fiscal years a funder could have reported on.

    An Indian FY runs April to March, and the CSR annexure for one is published
    months after it closes — so the newest year worth asking for is the one that
    has already ended, not the one we are in.
    """
    today = today or datetime.now(UTC).date()
    ended = today.year - 1 if today.month >= 4 else today.year - 2
    return tuple(f"FY{y}-{str(y + 1)[2:]}" for y in range(ended, ended - count, -1))
