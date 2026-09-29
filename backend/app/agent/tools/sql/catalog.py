"""The tables and columns the SQL tool may read — the allowlist, as data."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    type: str
    """As Postgres reports it, e.g. 'timestamp with time zone'."""
    note: str = ""
    """Meaning or gotcha, shown to the model by db_describe_table."""
    values: tuple[str, ...] = ()
    """The column's CHECK-constraint enum, verbatim. Free, exact, no row sampling."""
    cites: str | None = None
    """Citation kind this column's value yields: 'org' | 'funder' | 'grant' | 'score'."""
    heavy: bool = False
    """Large payload: selectable by name, but excluded from `SELECT *` expansion."""


@dataclass(frozen=True, slots=True)
class ForeignKey:
    column: str
    references: str
    """'table.column'."""


@dataclass(frozen=True, slots=True)
class Table:
    name: str
    description: str
    """One line; the model reads this in db_list_tables."""
    primary_key: tuple[str, ...]
    columns: tuple[Column, ...] = ()
    foreign_keys: tuple[ForeignKey, ...] = ()
    defects: tuple[str, ...] = ()
    """Known problems with the DATA in this table. See the module docstring."""


_TABLES: tuple[Table, ...] = (
    Table(
        name="chunks",
        description="Document text split for retrieval. Currently EMPTY.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("document_id", "documents.id"),),
        columns=(
            Column("id", "bigint"),
            Column("document_id", "bigint"),
            Column("chunk_index", "integer"),
            Column("content", "text", heavy=True, note="table is currently EMPTY - no rows to return"),
        ),
        defects=(
            "Table is empty (0 rows): no document has been chunked for retrieval yet, so nothing can be returned from it and joins through it drop every row.",
        ),
    ),
    Table(
        name="contacts",
        description="People at an org or a funder — exactly one owner.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("org_id", "orgs.id")),
        columns=(
            Column("id", "bigint"),
            Column("org_id", "bigint", cites="org", note="exactly one of org_id / funder_id is set (enforced by CHECK)"),
            Column("funder_id", "bigint", cites="funder", note="exactly one of org_id / funder_id is set (enforced by CHECK)"),
            Column("name", "text"),
            Column("role", "text"),
            Column("kind", "text", values=('office_bearer', 'programme', 'grants', 'other')),
            Column("verified", "boolean"),
            Column("notes", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("content_hash", "text"),
            Column("extractor_version", "text"),
            Column("is_public", "boolean"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
    ),
    Table(
        name="credential_events",
        description="What happened to a registration - registered, renewed, expired, cancelled, or a source saying it does not exist. Holds no ID number.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("org_id", "orgs.id"), ForeignKey("funder_id", "funders.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("id", "bigint"),
            Column("org_id", "bigint", cites="org"),
            Column("funder_id", "bigint", cites="funder"),
            Column("credential", "text", values=('pan', '12a', '80g', 'fcra', 'csr1', 'darpan', 'cin', 'reg_no')),
            Column("event", "text", note="'not_available' means a source says the registration does not exist", values=('registered', 'renewed', 'checked_active', 'restored', 'expired', 'suspended', 'cancelled', 'surrendered', 'superseded', 'not_available', 'not_found', 'check_blocked')),
            Column("event_date", "date"),
            Column("valid_until", "date"),
            Column("verified", "boolean", note="only verified events set the current status"),
            Column("notes", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
            Column("recorded_by", "uuid"),
            Column("recorded_at", "timestamp with time zone"),
        ),
        defects=(
            "Table is empty (0 rows): no credential history has been recorded, so every registration's current status is unknown rather than active.",
        ),
    ),
    Table(
        name="documents",
        description="Source documents held for an org or a funder.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("org_id", "orgs.id")),
        columns=(
            Column("id", "bigint"),
            Column("org_id", "bigint", cites="org"),
            Column("funder_id", "bigint", cites="funder"),
            Column("title", "text"),
            Column("doc_type", "text"),
            Column("content_md", "text", heavy=True),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("content_hash", "text"),
            Column("extractor_version", "text"),
            Column("is_public", "boolean", note="false = a private vault upload"),
            Column("status", "text", values=('requested', 'received', 'read', 'scored', 'verified')),
            Column("storage_path", "text"),
            Column("uploaded_by", "uuid"),
            Column("is_ai_generated", "boolean"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("archive_url", "text"),
            Column("created_at", "timestamp with time zone"),
        ),
        defects=(
            "53 of 96 rows have neither org_id nor funder_id set, so ownership filters silently under-count. There is no CHECK enforcing exactly-one-owner on this table.",
        ),
    ),
    Table(
        name="extraction_log",
        description="Audit trail of what was extracted from which document.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("document_id", "documents.id"),),
        columns=(
            Column("id", "bigint"),
            Column("document_id", "bigint"),
            Column("target_table", "text"),
            Column("target_pk", "text"),
            Column("extractor_version", "text"),
            Column("model", "text"),
            Column("confidence", "numeric"),
            Column("extracted_at", "timestamp with time zone"),
        ),
        defects=(
            "Table is empty (0 rows): nothing has been recorded about which document a field was extracted from.",
        ),
    ),
    Table(
        name="fit_score_items",
        description="Per-criterion scores making up a fit_score. Join table.",
        primary_key=('fit_score_id', 'criterion_id'),
        foreign_keys=(ForeignKey("criterion_id", "rubric_criteria.id"), ForeignKey("fit_score_id", "fit_scores.id")),
        columns=(
            Column("fit_score_id", "bigint", cites="score"),
            Column("criterion_id", "bigint"),
            Column("score", "integer"),
            Column("justification", "text"),
        ),
    ),
    Table(
        name="fit_scores",
        description="One rubric assessment of how well an org fits a funder.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("org_id", "orgs.id"), ForeignKey("rubric_id", "rubrics.id")),
        columns=(
            Column("id", "bigint", cites="score"),
            Column("org_id", "bigint", cites="org"),
            Column("funder_id", "bigint", cites="funder"),
            Column("rubric_id", "bigint"),
            Column("total_score", "integer", note="out of max_score, on the rubric named by rubric_id"),
            Column("max_score", "integer"),
            Column("scored_by", "text", note="who produced the assessment; 'manual' for hand-scoring"),
            Column("scored_at", "timestamp with time zone"),
            Column("notes", "text"),
            Column("valid_from", "timestamp with time zone"),
            Column("valid_to", "timestamp with time zone"),
        ),
    ),
    Table(
        name="funder_csr_spend",
        description="A funder's CSR spend by sector and place per fiscal year: either an aggregate or one named project.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("program_id", "programs.id"), ForeignKey("csr_sector_id", "tags.id"), ForeignKey("state_location_id", "locations.id"), ForeignKey("district_location_id", "locations.id"), ForeignKey("agency_org_id", "orgs.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("id", "bigint"),
            Column("funder_id", "bigint", cites="funder"),
            Column("fiscal_year", "text", note="period label, always 'FYyyyy-yy'"),
            Column("program_id", "bigint"),
            Column("csr_sector_id", "bigint"),
            Column("state_location_id", "bigint"),
            Column("district_location_id", "bigint"),
            Column("designation", "text", note="the total covers only places with this designation, e.g. 'aspirational_district'"),
            Column("project_name", "text", note="NULL on an aggregate row; set on a single project"),
            Column("implementing_agency", "text"),
            Column("agency_csr1", "text"),
            Column("agency_org_id", "bigint", cites="org"),
            Column("via_agency", "boolean"),
            Column("is_ongoing", "boolean"),
            Column("amount", "numeric"),
            Column("project_count", "integer"),
            Column("notes", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
        defects=(
            "Sparse: rows arrive only from research that has been promoted, one funder at a time, so most funders have none. A zero total means 'not recorded', never 'spent nothing'.",
        ),
    ),
    Table(
        name="funder_csr_years",
        description="A funder's statutory CSR obligation and spend, one row per fiscal year, following the annual CSR return.",
        primary_key=('funder_id', 'fiscal_year'),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("funder_id", "bigint", cites="funder"),
            Column("fiscal_year", "text", note="period label, always 'FYyyyy-yy'"),
            Column("section_135_applicable", "boolean"),
            Column("average_net_profit", "numeric"),
            Column("prescribed_csr", "numeric"),
            Column("spent_on_projects", "numeric"),
            Column("admin_overheads", "numeric"),
            Column("impact_assessment_cost", "numeric"),
            Column("total_spent", "numeric"),
            Column("unspent_transferred", "numeric"),
            Column("excess_spent", "numeric"),
            Column("impact_assessment_done", "boolean"),
            Column("notes", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
        defects=(
            "Sparse: filled a funder and a year at a time from promoted research, so a missing year means nobody has researched it, not that the funder filed nothing.",
        ),
    ),
    Table(
        name="funder_footprints",
        description="Where a funder's theme actually ran, by place and fiscal year. The strongest evidence of a funder's real geography.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("program_id", "programs.id"), ForeignKey("location_id", "locations.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("id", "bigint"),
            Column("funder_id", "bigint", cites="funder"),
            Column("program_id", "bigint"),
            Column("fiscal_year", "text", note="period label, always 'FYyyyy-yy'"),
            Column("location_id", "bigint"),
            Column("name_as_printed", "text", note="the place name as the report spelled it"),
            Column("notes", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
        defects=(
            "Sparse: a funder appears here only where a source named a place precisely enough to resolve. Absence is silence, not evidence of no activity, and funder_locations holds STATED priorities, which is a different claim.",
        ),
    ),
    Table(
        name="funder_identifiers",
        description="Statutory registration IDs for a funder. One row per ID.",
        primary_key=('id_type', 'id_value'),
        foreign_keys=(ForeignKey("funder_id", "funders.id"),),
        columns=(
            Column("funder_id", "bigint", cites="funder"),
            Column("id_type", "text", values=('pan', 'cin', 'csr1', 'darpan', 'reg_no', 'domain', 'name')),
            Column("id_value", "text"),
            Column("verified", "boolean"),
            Column("source_url", "text"),
            Column("is_current", "boolean", note="false = superseded"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("archive_url", "text"),
        ),
    ),
    Table(
        name="funder_locations",
        description="Geographies a funder gives in. Join table.",
        primary_key=('funder_id', 'location_id'),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("location_id", "locations.id")),
        columns=(
            Column("funder_id", "bigint", cites="funder"),
            Column("location_id", "bigint"),
            Column("role", "text", note="'priority' is a STATED focus, not evidence of funding - see funder_footprints and grant_locations for where a funder actually gave", values=('registered', 'operates', 'funds', 'priority')),
            Column("valid_from", "date"),
            Column("valid_to", "date"),
            Column("note", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
    ),
    Table(
        name="funder_partners",
        description="Organisations a funder named as a partner, per theme and fiscal year. Repeats across years show renewals.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("program_id", "programs.id"), ForeignKey("org_id", "orgs.id"), ForeignKey("partner_funder_id", "funders.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("id", "bigint"),
            Column("funder_id", "bigint", cites="funder"),
            Column("program_id", "bigint"),
            Column("fiscal_year", "text", note="period label, always 'FYyyyy-yy'"),
            Column("partner_name", "text"),
            Column("partner_canonical", "text", note="one spelling per partner; count renewals on this, not partner_name"),
            Column("org_id", "bigint", cites="org"),
            Column("partner_funder_id", "bigint", cites="funder"),
            Column("partner_csr1", "text"),
            Column("partner_kind", "text", values=('ngo', 'foundation', 'university', 'research', 'government', 'armed_forces', 'hospital', 'network', 'company', 'other')),
            Column("notes", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
        defects=(
            "Sparse: partners come from promoted research, so zero shared partners means 'not recorded', never 'no partners'. A row here is a named relationship, NOT evidence that money changed hands.",
        ),
    ),
    Table(
        name="funder_tags",
        description="A funder's focus sectors/themes. Join table.",
        primary_key=('funder_id', 'tag_id'),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("tag_id", "tags.id")),
        columns=(
            Column("funder_id", "bigint", cites="funder"),
            Column("tag_id", "bigint"),
            Column("role", "text", values=('primary', 'secondary')),
            Column("is_inferred", "boolean"),
            Column("tagged_by", "text"),
            Column("note", "text"),
        ),
    ),
    Table(
        name="funders",
        description="Funders: corporate CSR arms, private foundations, family trusts.",
        primary_key=('id',),
        columns=(
            Column("id", "bigint", cites="funder"),
            Column("slug", "text"),
            Column("name", "text", note="trigram-indexed; use similarity() for fuzzy matching"),
            Column("funder_type", "text", note="free text: corporate_csr | private_foundation | family_trust_network | ..."),
            Column("section_135_bound", "boolean", note="NULL means unknown, not false"),
            Column("website", "text"),
            Column("profile", "jsonb", heavy=True),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("content_hash", "text"),
            Column("extractor_version", "text"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("archive_url", "text"),
            Column("registry_status", "text", note="'hidden' rows are staff-only; 'placeholder' is a stub, not a profile", values=('placeholder', 'in_vetting', 'full_profile', 'hidden')),
            Column("parent_id", "bigint", note="the company a foundation belongs to, e.g. Axis Bank Foundation -> Axis Bank Limited"),
        ),
    ),
    Table(
        name="grant_locations",
        description="Where a grant was actually spent. Join table.",
        primary_key=('grant_id', 'location_id'),
        foreign_keys=(ForeignKey("grant_id", "grants.id"), ForeignKey("location_id", "locations.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("grant_id", "bigint", cites="grant"),
            Column("location_id", "bigint"),
            Column("note", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
        defects=(
            "Table is empty (0 rows): no grant has a place yet, so an INNER JOIN from grants through this table returns nothing. Outer-join it, or read grants directly.",
        ),
    ),
    Table(
        name="grants",
        description="Researched funding relationships: who funded whom, when, how much.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("org_id", "orgs.id"), ForeignKey("program_id", "programs.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("id", "bigint", cites="grant"),
            Column("funder_id", "bigint", cites="funder"),
            Column("org_id", "bigint", cites="org"),
            Column("program_id", "bigint"),
            Column("title", "text"),
            Column("amount", "numeric", note="NULL where the amount was never made public - not zero"),
            Column("currency", "text", note="defaults to INR"),
            Column("start_date", "date"),
            Column("end_date", "date"),
            Column("status", "text", values=('active', 'concluded', 'unconfirmed', 'dormant')),
            Column("outcomes", "jsonb", heavy=True),
            Column("notes", "text"),
            Column("valid_from", "timestamp with time zone"),
            Column("valid_to", "timestamp with time zone"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("content_hash", "text"),
            Column("extractor_version", "text"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
    ),
    Table(
        name="location_designations",
        description="Designations that funders prioritise: aspirational_district, north_east.",
        primary_key=('location_id', 'designation'),
        foreign_keys=(ForeignKey("location_id", "locations.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("location_id", "bigint"),
            Column("designation", "text"),
            Column("programme", "text"),
            Column("list_rank", "integer"),
            Column("name_as_listed", "text"),
            Column("valid_from", "date"),
            Column("valid_to", "date"),
            Column("notes", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
        defects=(
            "Table is empty (0 rows): no designation has been loaded, so no place can be shown as prioritised and a filter on this returns nothing.",
        ),
    ),
    Table(
        name="locations",
        description="Place hierarchy: country > state > district. Self-referencing via parent_id.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("parent_id", "locations.id"),),
        columns=(
            Column("id", "bigint"),
            Column("kind", "text", values=('country', 'region', 'state', 'district', 'block', 'village')),
            Column("name", "text", note="stored UPPER CASE, e.g. 'DIMAPUR'. Compare case-insensitively (ILIKE)"),
            Column("parent_id", "bigint", note="-> locations.id. district -> state -> country"),
            Column("lgd_code", "text", note="Local Government Directory code, unique within a kind"),
            Column("aliases", "text[]", note="other spellings of the same place; match against these too"),
        ),
    ),
    Table(
        name="metrics",
        description="Impact and reach figures for an org OR a funder. Rows sharing chain_key form one results chain.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("org_id", "orgs.id"), ForeignKey("funder_id", "funders.id"), ForeignKey("program_id", "programs.id"), ForeignKey("grant_id", "grants.id"), ForeignKey("location_id", "locations.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("id", "bigint"),
            Column("org_id", "bigint", cites="org"),
            Column("funder_id", "bigint", cites="funder"),
            Column("program_id", "bigint"),
            Column("grant_id", "bigint", cites="grant"),
            Column("location_id", "bigint"),
            Column("name", "text"),
            Column("value", "numeric"),
            Column("target", "numeric"),
            Column("unit", "text"),
            Column("period", "text"),
            Column("stage", "text", values=('input', 'output', 'adoption', 'outcome', 'sustained_outcome', 'impact', 'sroi')),
            Column("chain_key", "text", note="rows sharing this form one results chain, ordered by sequence"),
            Column("sequence", "integer"),
            Column("baseline", "numeric"),
            Column("comparison_value", "numeric"),
            Column("method", "text", values=('self_reported', 'monitoring_data', 'survey', 'comparison_study', 'third_party_evaluation', 'estimate')),
            Column("is_self_reported", "boolean", note="true by default; check method before quoting a figure as evidence"),
            Column("notes", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
        defects=(
            "Sparse: figures arrive from promoted research and are mostly self-reported — check `method` before quoting one as evidence. grants.outcomes holds a little more as jsonb; a zero here is not evidence an organisation measures nothing.",
        ),
    ),
    Table(
        name="news_mentions",
        description="GDELT news hits. Rarely linked to an entity — read the caveat.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("grant_id", "grants.id"), ForeignKey("org_id", "orgs.id")),
        columns=(
            Column("id", "bigint"),
            Column("url", "text"),
            Column("title", "text"),
            Column("seendate", "timestamp with time zone"),
            Column("domain", "text"),
            Column("language", "text"),
            Column("sourcecountry", "text"),
            Column("topic", "text"),
            Column("funder_id", "bigint", cites="funder"),
            Column("org_id", "bigint", cites="org"),
            Column("grant_id", "bigint", cites="grant"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("kind", "text", values=('news', 'press', 'social')),
            Column("platform", "text"),
            Column("summary", "text"),
            Column("sentiment", "text", values=('positive', 'neutral', 'negative')),
            Column("review_status", "text", note="only 'vetted' items are public", values=('pending', 'vetted', 'rejected')),
            Column("reviewed_by", "uuid"),
            Column("reviewed_at", "timestamp with time zone"),
            Column("archive_url", "text"),
        ),
        defects=(
            "org_id, funder_id and grant_id are NULL for all 118 rows. Any JOIN or filter on them returns zero rows. A zero result here means 'not linked in the data', NEVER 'no news exists'.",
        ),
    ),
    Table(
        name="org_financials",
        description="An organisation's income and spend, one row per fiscal year.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("org_id", "orgs.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("id", "bigint"),
            Column("org_id", "bigint", cites="org"),
            Column("fiscal_year", "text", note="period label, always 'FYyyyy-yy'"),
            Column("total_income", "numeric"),
            Column("program_spend", "numeric"),
            Column("non_program_spend", "numeric"),
            Column("foreign_contribution", "numeric"),
            Column("is_audited", "boolean"),
            Column("notes", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
        defects=(
            "Table is empty (0 rows): no accounts have been loaded, so income and spend questions cannot be answered and eligibility gates on revenue cannot be evaluated.",
        ),
    ),
    Table(
        name="org_identifiers",
        description="Statutory registration IDs for an org (PAN, FCRA, Darpan...). One row per ID.",
        primary_key=('id_type', 'id_value'),
        foreign_keys=(ForeignKey("org_id", "orgs.id"),),
        columns=(
            Column("org_id", "bigint", cites="org"),
            Column("id_type", "text", values=('pan', '12a', '80g', 'fcra', 'csr1', 'darpan', 'cin', 'reg_no')),
            Column("id_value", "text"),
            Column("verified", "boolean"),
            Column("source_url", "text"),
            Column("is_current", "boolean", note="false = superseded, e.g. an old 12A after re-registration"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
            Column("is_public", "boolean", note="false means the number is on file but not published"),
            Column("notes", "text"),
        ),
    ),
    Table(
        name="org_locations",
        description="Where an org is registered or operates. Join table.",
        primary_key=('org_id', 'location_id'),
        foreign_keys=(ForeignKey("location_id", "locations.id"), ForeignKey("org_id", "orgs.id")),
        columns=(
            Column("org_id", "bigint", cites="org"),
            Column("location_id", "bigint"),
            Column("role", "text", values=('registered', 'operates', 'funds')),
            Column("valid_from", "date"),
            Column("valid_to", "date"),
            Column("note", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
    ),
    Table(
        name="org_tags",
        description="Which sector/population/theme tags an org carries. Join table.",
        primary_key=('org_id', 'tag_id'),
        foreign_keys=(ForeignKey("org_id", "orgs.id"), ForeignKey("tag_id", "tags.id")),
        columns=(
            Column("org_id", "bigint", cites="org"),
            Column("tag_id", "bigint"),
            Column("role", "text", values=('primary', 'secondary')),
            Column("is_inferred", "boolean"),
            Column("tagged_by", "text"),
            Column("note", "text"),
        ),
    ),
    Table(
        name="orgs",
        description="CSOs/NGOs in the FFRH cohort. One row per organisation.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("registered_location_id", "locations.id"),),
        columns=(
            Column("id", "bigint", cites="org"),
            Column("slug", "text", note="stable url key, lower-case, e.g. 'kabil'"),
            Column("name", "text", note="trigram-indexed; use similarity(name, 'x') > 0.3 for fuzzy matching"),
            Column("org_kind", "text", values=('cso', 'intermediary', 'government')),
            Column("cohort", "text", note="which FFRH cohort the org belongs to"),
            Column("legal_form", "text", note="FREE TEXT, not an enum - values like 'Public Charitable Trust'. Profile it before filtering"),
            Column("registration_date", "date"),
            Column("registered_location_id", "bigint", note="-> locations.id, usually a district. See the locations caveat"),
            Column("contact", "jsonb", heavy=True),
            Column("sections", "jsonb", heavy=True),
            Column("profile", "jsonb", heavy=True),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("content_hash", "text"),
            Column("extractor_version", "text"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("archive_url", "text"),
            Column("registry_status", "text", note="'hidden' rows are staff-only; 'placeholder' is a stub, not a profile", values=('placeholder', 'in_vetting', 'full_profile', 'hidden')),
        ),
    ),
    Table(
        name="program_locations",
        description="Where a programme operates. Join table.",
        primary_key=('program_id', 'location_id'),
        foreign_keys=(ForeignKey("location_id", "locations.id"), ForeignKey("program_id", "programs.id")),
        columns=(
            Column("program_id", "bigint"),
            Column("location_id", "bigint"),
            Column("role", "text", values=('registered', 'operates', 'funds')),
            Column("valid_from", "date"),
            Column("valid_to", "date"),
            Column("note", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
        defects=(
            "Table is empty (0 rows): no programme has a location, so an INNER JOIN from programs through this table silently returns nothing. Outer-join it, or read programs directly.",
        ),
    ),
    Table(
        name="program_tags",
        description="Tags on a programme. Join table.",
        primary_key=('program_id', 'tag_id'),
        foreign_keys=(ForeignKey("program_id", "programs.id"), ForeignKey("tag_id", "tags.id")),
        columns=(
            Column("program_id", "bigint"),
            Column("tag_id", "bigint"),
            Column("role", "text", values=('primary', 'secondary')),
            Column("is_inferred", "boolean"),
            Column("tagged_by", "text"),
            Column("note", "text"),
        ),
        defects=(
            "Table is empty (0 rows): no programme has been tagged, so an INNER JOIN from programs through this table silently returns nothing. Outer-join it, or read programs directly.",
        ),
    ),
    Table(
        name="programs",
        description="A programme run by an org, or a funding programme run by a funder — exactly one owner.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("org_id", "orgs.id"), ForeignKey("parent_id", "programs.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("id", "bigint"),
            Column("org_id", "bigint", cites="org", note="exactly one of org_id / funder_id is set (enforced by CHECK)"),
            Column("funder_id", "bigint", cites="funder", note="exactly one of org_id / funder_id is set (enforced by CHECK)"),
            Column("name", "text"),
            Column("description", "text"),
            Column("status", "text"),
            Column("start_date", "date"),
            Column("end_date", "date"),
            Column("details", "jsonb", heavy=True),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("content_hash", "text"),
            Column("extractor_version", "text"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
            Column("parent_id", "bigint", note="hierarchy within one owner"),
            Column("kind", "text", note="a funder's own rows run theme > programme > phase, linked by parent_id", values=('theme', 'programme', 'phase', 'project')),
            Column("is_enabler", "boolean"),
        ),
    ),
    Table(
        name="proposal_templates",
        description="A funder's application form, RFP, due-diligence checklist or budget format.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("rfp_id", "rfps.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("id", "bigint"),
            Column("funder_id", "bigint", cites="funder"),
            Column("rfp_id", "bigint"),
            Column("name", "text"),
            Column("kind", "text", values=('application', 'rfp', 'due_diligence', 'budget', 'reporting', 'site_visit')),
            Column("version", "text"),
            Column("notes", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
        defects=(
            "Table is empty (0 rows): no funder's form has been loaded yet.",
        ),
    ),
    Table(
        name="reference_figures",
        description="External benchmarks for budgeting: cost per beneficiary, overhead norms, salary ranges.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("tag_id", "tags.id"), ForeignKey("location_id", "locations.id"), ForeignKey("funder_id", "funders.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("id", "bigint"),
            Column("kind", "text", values=('cost_per_beneficiary', 'overhead_norm', 'salary_benchmark', 'unit_cost', 'outcome_rate', 'sroi_ratio', 'district_indicator', 'state_indicator', 'other')),
            Column("name", "text"),
            Column("value", "numeric"),
            Column("value_text", "text"),
            Column("unit", "text"),
            Column("tag_id", "bigint"),
            Column("location_id", "bigint"),
            Column("funder_id", "bigint", cites="funder"),
            Column("period", "text"),
            Column("notes", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
        defects=(
            "Table is empty (0 rows): no benchmark has been loaded yet.",
        ),
    ),
    Table(
        name="rfp_locations",
        description="Geographies an RFP covers. Join table.",
        primary_key=('rfp_id', 'location_id'),
        foreign_keys=(ForeignKey("location_id", "locations.id"), ForeignKey("rfp_id", "rfps.id")),
        columns=(
            Column("rfp_id", "bigint"),
            Column("location_id", "bigint"),
            Column("role", "text", values=('registered', 'operates', 'funds')),
            Column("valid_from", "date"),
            Column("valid_to", "date"),
            Column("note", "text"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
        defects=(
            "Table is empty (0 rows) because rfps is empty.",
        ),
    ),
    Table(
        name="rfp_matches",
        description="Which orgs were flagged as a fit for an RFP. Join table with a score.",
        primary_key=('rfp_id', 'org_id'),
        foreign_keys=(ForeignKey("org_id", "orgs.id"), ForeignKey("rfp_id", "rfps.id")),
        columns=(
            Column("rfp_id", "bigint"),
            Column("org_id", "bigint", cites="org"),
            Column("match_score", "numeric"),
            Column("match_notes", "text"),
            Column("status", "text", values=('flagged', 'reviewed', 'dismissed')),
            Column("matched_by", "text"),
            Column("matched_at", "timestamp with time zone"),
            Column("week_of", "date"),
        ),
        defects=(
            "Table is empty (0 rows) because rfps is empty; no org has been matched to a call for proposals yet.",
        ),
    ),
    Table(
        name="rfp_tags",
        description="Tags on an RFP. Join table.",
        primary_key=('rfp_id', 'tag_id'),
        foreign_keys=(ForeignKey("rfp_id", "rfps.id"), ForeignKey("tag_id", "tags.id")),
        columns=(
            Column("rfp_id", "bigint"),
            Column("tag_id", "bigint"),
            Column("role", "text", values=('primary', 'secondary')),
            Column("is_inferred", "boolean"),
            Column("tagged_by", "text"),
            Column("note", "text"),
        ),
        defects=(
            "Table is empty (0 rows) because rfps is empty.",
        ),
    ),
    Table(
        name="rfps",
        description="Open calls for proposals published by funders.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"),),
        columns=(
            Column("id", "bigint"),
            Column("funder_id", "bigint", cites="funder"),
            Column("title", "text"),
            Column("url", "text"),
            Column("status", "text", values=('open', 'closed', 'removed')),
            Column("deadline", "date"),
            Column("amount_min", "numeric"),
            Column("amount_max", "numeric"),
            Column("eligibility", "jsonb", heavy=True),
            Column("details", "jsonb", heavy=True),
            Column("valid_from", "timestamp with time zone"),
            Column("valid_to", "timestamp with time zone"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("content_hash", "text"),
            Column("extractor_version", "text"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
        defects=(
            "Table is empty (0 rows): the RFP subsystem is built but no calls for proposals have been loaded. A zero result says nothing about whether such RFPs exist.",
        ),
    ),
    Table(
        name="rubric_criteria",
        description="The individual criteria of a rubric, with their point values.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("parent_id", "rubric_criteria.id"), ForeignKey("rubric_id", "rubrics.id")),
        columns=(
            Column("id", "bigint"),
            Column("rubric_id", "bigint"),
            Column("parent_id", "bigint"),
            Column("code", "text"),
            Column("label", "text"),
            Column("points", "integer"),
            Column("guiding_question", "text"),
        ),
    ),
    Table(
        name="rubrics",
        description="A versioned scoring rubric.",
        primary_key=('id',),
        columns=(
            Column("id", "bigint"),
            Column("version", "text"),
            Column("name", "text"),
            Column("total_points", "integer"),
            Column("notes", "text"),
            Column("created_at", "timestamp with time zone"),
        ),
    ),
    Table(
        name="score_adjustments",
        description="Manual hand-vetting changes to a fit_score's criterion scores.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("criterion_id", "rubric_criteria.id"), ForeignKey("fit_score_id", "fit_scores.id")),
        columns=(
            Column("id", "bigint"),
            Column("fit_score_id", "bigint", cites="score"),
            Column("criterion_id", "bigint"),
            Column("old_score", "integer"),
            Column("new_score", "integer"),
            Column("reason", "text"),
            Column("adjusted_at", "timestamp with time zone"),
        ),
    ),
    Table(
        name="tags",
        description="The controlled vocabulary of sectors, populations and themes.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("parent_id", "tags.id"),),
        columns=(
            Column("id", "bigint"),
            Column("slug", "text"),
            Column("label", "text", note="the human-readable tag, e.g. 'Education'. Profile it before filtering"),
            Column("kind", "text", values=('sdg', 'sector', 'population', 'darpan_sector', 'theme', 'domain', 'cell', 'csr_sector', 'scheme')),
            Column("parent_id", "bigint"),
            Column("taxonomy_ref", "text"),
            Column("domain", "text", note="'livelihoods' | 'health' | 'education'; required for kind 'domain' and 'cell'"),
            Column("code", "text"),
            Column("level", "text"),
            Column("description", "text"),
            Column("meta", "jsonb", note="crosswalk: sdgs, sectors, maps_to, refs"),
            Column("status", "text", note="'deprecated' rows are kept so old links resolve - exclude them from vocabularies", values=('draft', 'active', 'deprecated')),
            Column("replaced_by", "bigint"),
            Column("sort_order", "integer"),
        ),
    ),
    Table(
        name="template_items",
        description="One section, question, criterion, eligibility gate or required document of a template.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("template_id", "proposal_templates.id"),),
        columns=(
            Column("id", "bigint"),
            Column("template_id", "bigint"),
            Column("ord", "integer"),
            Column("item_kind", "text", values=('section', 'question', 'criterion', 'eligibility', 'document')),
            Column("code", "text"),
            Column("heading", "text"),
            Column("guidance", "text"),
            Column("word_limit", "integer"),
            Column("char_limit", "integer"),
            Column("points", "numeric"),
            Column("required", "boolean"),
            Column("check_rule", "jsonb", note="a rule the database can test; NULL means a person judges it"),
        ),
        defects=(
            "Table is empty (0 rows) because proposal_templates is empty.",
        ),
    ),

)

CATALOG: Mapping[str, Table] = MappingProxyType({t.name: t for t in _TABLES})

TABLE_NAMES: frozenset[str] = frozenset(CATALOG)

COLUMNS: Mapping[str, Mapping[str, Column]] = MappingProxyType(
    {name: MappingProxyType({c.name: c for c in t.columns}) for name, t in CATALOG.items()}
)

# What sqlglot's qualify() needs: EVERY column, including heavy ones. A reduced schema here would make a
# heavy column unresolvable when asked for by name, which is not the intent — `*` should omit them, naming.
SQLGLOT_SCHEMA: dict[str, dict[str, str]] = {
    name: {c.name: c.type for c in t.columns} for name, t in CATALOG.items()
}

STAR_COLUMNS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {name: tuple(c.name for c in t.columns if not c.heavy) for name, t in CATALOG.items()}
)

# (table, column) -> citation kind. Set on primary keys AND on every foreign key pointing at one, so a row
# from programs or contacts is citable through the org_id/funder_id it already carries.
CITE_COLUMNS: Mapping[tuple[str, str], str] = MappingProxyType(
    {(name, c.name): c.cites for name, t in CATALOG.items() for c in t.columns if c.cites}
)

DEFECTS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {name: t.defects for name, t in CATALOG.items() if t.defects}
)

# Tables that exist in the database and are deliberately NOT in the catalog. Named so verify_against_db()
# can stay quiet about them while still reporting a genuinely new table that nobody has made a decision.
KNOWN_EXCLUDED: frozenset[str] = frozenset(
    {
        # Serialized conversation history — every user's full chat, in this same
        # database. The single most sensitive thing here.
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "checkpoint_migrations",
        # Account records and who-talked-to-what.
        "users",
        "threads",
        # Access control, not registry data: it maps users (excluded above) to orgs.
        "org_members",
        # Private org data with no per-caller filter yet: every org's drafts,
        # amounts and decisions. Catalogue it when queries run as the caller.
        "proposals",
        # Importer bookkeeping, not catalog data: run history and the review queue.
        # Sangam Import has its own tools for these; Ask Sangam has no use for them.
        "ingest_runs",
        "ingest_run_items",
        "ingest_source_proposals",
        "entity_research",
        "resolution_queue",
        # Infrastructure.
        "schema_migrations",
        "graph_ingest_log",
    }
)


def _self_check() -> None:
    """Fail at import if the catalog contradicts itself."""
    for name, table in CATALOG.items():
        cols = COLUMNS[name]
        if not table.columns:
            raise ValueError(f"catalog: {name} has no columns")
        if not table.primary_key:
            raise ValueError(f"catalog: {name} has no primary key")
        for pk in table.primary_key:
            if pk not in cols:
                raise ValueError(f"catalog: {name}.{pk} is a primary key but is not listed")
        for fk in table.foreign_keys:
            if fk.column not in cols:
                raise ValueError(f"catalog: {name}.{fk.column} is a foreign key but is not listed")
            target_table, _, target_col = fk.references.partition(".")
            if target_table not in CATALOG:
                raise ValueError(
                    f"catalog: {name}.{fk.column} references {fk.references}, "
                    f"but {target_table} is not in the catalog"
                )
            if target_col not in COLUMNS[target_table]:
                raise ValueError(f"catalog: {name}.{fk.column} references missing {fk.references}")
        for column in table.columns:
            if column.cites and column.cites not in {"org", "funder", "grant", "score"}:
                raise ValueError(f"catalog: {name}.{column.name} cites unknown kind {column.cites!r}")


_self_check()


async def verify_against_db(conn: Any) -> list[str]:
    """Problems found comparing the catalog to the live schema; empty when clean."""
    rows = await (
        await conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        )
    ).fetchall()

    live: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        live[row["table_name"]].add(row["column_name"])

    problems: list[str] = []
    for name, table in CATALOG.items():
        if name not in live:
            problems.append(f"catalog table {name!r} does not exist in the database")
            continue
        missing = sorted({c.name for c in table.columns} - live[name])
        if missing:
            problems.append(f"{name}: catalog lists columns the database does not have: {', '.join(missing)}")
    return problems


def undeclared_tables(live_table_names: set[str]) -> list[str]:
    """Live tables that are neither in the catalog nor knowingly excluded."""
    return sorted(live_table_names - TABLE_NAMES - KNOWN_EXCLUDED)
