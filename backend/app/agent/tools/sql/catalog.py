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
    """Citation kind this column's value yields: 'org' | 'funder' | 'activity' | 'score'."""
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


# The evidence tier on every CSO table Import writes; values are 0033's CHECK enums, verbatim.
_SOURCE_TYPES = ('registry', 'org_document', 'funder', 'staff_dataset', 'manual_check', 'prior_research',
                 'aggregator', 'seed')
_TIER = (
    Column("source_type", "text", note="the kind of source the row's values came from. Strongest first: registry = manual_check > org_document > funder > staff_dataset > prior_research > aggregator > seed. NULL = not ranked: entered by a person, or written before tiers", values=_SOURCE_TYPES),
    Column("evidence", "text", note="'evidenced' only when a document itself states the fact (a certificate, an audited statement, a dated return); 'claimed' otherwise. aggregator and prior_research rows are always 'claimed'", values=('evidenced', 'claimed')),
)
_TIER_DEFECT = (
    "source_type and evidence describe the ROW: they name the strongest source that has stated anything on "
    "it, NOT the source of every column. Other columns of the same row may have been filled by weaker "
    "sources and are not labelled separately. A row whose evidence is 'claimed' - every "
    "aggregator and prior_research row among them - is never presented as fact: say 'claimed by "
    "<source_type>' beside it, and never let it settle an eligibility question."
)

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
            *_TIER,
        ),
        defects=(_TIER_DEFECT,),
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
            Column("doc_type", "text", note="free text, except three values written by their own path: 'funder_eligibility' (a funder's standing eligibility, verbatim in content_md), 'proposal_template' (a funder's application form), 'source_dataset' (a staff-only file with no content_md). A CSO's own: trust_deed, registration_certificate, exemption_order (12AB/80G: Forms 10AC/10AD), exemption_application (a Form 10AB acknowledgement), csr1_approval, fcra_certificate, fcra_return, audit_report, annual_report, policy, manual_check_evidence (a screenshot or archive of a registry check)"),
            Column("content_md", "text", heavy=True),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("content_hash", "text"),
            Column("extractor_version", "text"),
            Column("is_public", "boolean", note="false = a private vault upload, a hidden funder's eligibility document, or a staff dataset (doc_type 'source_dataset') - all staff or owner only"),
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
            "Rows with is_public = false are private Doc Vault uploads belonging to one organisation, or the eligibility document (doc_type 'funder_eligibility') of a hidden funder, which is staff only. This tool applies no per-caller filter: their content_md and storage_path are readable by every user. Deliberate and temporary - it ends when queries run as the caller (docs/DATA_PLATFORM.md, 'Authorization: run every query as the caller'). Until then, do not quote a private upload to anyone outside the organisation that owns it, nor a hidden funder's eligibility document to anyone but staff.",
            "doc_type 'source_dataset' rows are staff-only workbooks with no content_md; their contents are read only by Sangam Import. Facts promoted from them cite a non-resolving https://staff-sources.sangam.invalid/ URL by design - never present that URL as a link.",
            "doc_type 'funder_eligibility' is sparse: filled from promoted research one funder at a time, so no eligibility document means nobody has read that funder's policy - never that it sets no conditions.",
            "doc_type 'funder_eligibility' is a funder's STANDING policy only. A requirement printed in one open call lives in rfps.eligibility, and the same sentence can legitimately appear in both. Counting across the two double-counts.",
            "doc_type 'funder_eligibility' states a bar; it does not apply it: these are the funder's published conditions, and nothing here judges whether any organisation meets them.",
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
            Column(
                "local_area_spent", "numeric",
                note="spent in the local area of the company's operations, INR, as the MCA return reports it",
            ),
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
        name="funder_activity",
        description="One line of a funder's CSR filing, annual report or partner list per fiscal year: a spend line, a place the work ran, a named partner, or the funder's own programme figure. `kind` says which. A grant to an organisation is a 'partner' line with partner_org_id set; there is no grants table.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("program_id", "programs.id"), ForeignKey("domain_tag_id", "tags.id"), ForeignKey("theme_tag_id", "tags.id"), ForeignKey("csr_sector_id", "tags.id"), ForeignKey("state_location_id", "locations.id"), ForeignKey("location_id", "locations.id"), ForeignKey("partner_org_id", "orgs.id"), ForeignKey("partner_funder_id", "funders.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("id", "bigint", cites="activity"),
            Column("funder_id", "bigint", cites="funder", note="for a statutory filing, the corporate parent that filed it; a foundation is its child through funders.parent_id"),
            Column("kind", "text", note="'spend' a filing line with an amount; 'footprint' a place the work ran; 'partner' a named partner; 'programme' the funder's OWN total for one programme component. Always filter on kind", values=('spend', 'footprint', 'partner', 'programme')),
            Column("fiscal_year", "text", note="period label, always 'FYyyyy-yy'"),
            Column("program_id", "bigint", note="the funder's programs row; required on kind 'programme'"),
            Column("domain_tag_id", "bigint", note="tags row of kind 'domain' (livelihoods, health, education, environment, others). Set by the Import writer on spend and programme lines; NULL on spend lines 0031 copied from the old table. INFERRED unless classification_confirmed"),
            Column("theme_tag_id", "bigint", note="tags row of kind 'theme' or 'sub_theme', at the most specific level the evidence supports; NULL means the line gave nothing to go on, not 'no theme'"),
            Column("classified_by", "text", note="what the domain and theme rest on", values=('filed_sector', 'project_name', 'partner', 'report')),
            Column("classification_note", "text", note="the evidence for the classification in a few words"),
            Column("classification_confirmed", "boolean", note="true only after a person vetted the domain and theme; report totals as 'confirmed' or 'including inferred'"),
            Column("csr_sector_id", "bigint", note="the Schedule VII sector AS FILED (tags kind 'csr_sector'); filings misfile often, so prefer domain_tag_id for 'what was this spent on'"),
            Column("state_location_id", "bigint"),
            Column("location_id", "bigint", note="the most specific place below the state, usually a district"),
            Column("name_as_printed", "text", note="the place name as the source spelled it"),
            Column("project_name", "text", note="NULL on an aggregate spend line; set on a single project; on a partner line, the grant's title"),
            Column("designation", "text", note="the total covers only places with this designation, e.g. 'aspirational_district'"),
            Column("implementation_mode", "text", values=('direct', 'implementing_agency', 'own_trust_or_section8', 'not_stated')),
            Column("partner_name", "text", note="the implementing agency or named partner, as printed"),
            Column("partner_canonical", "text", note="one spelling per partner; count renewals on this, not partner_name"),
            Column("partner_org_id", "bigint", cites="org"),
            Column("partner_funder_id", "bigint", cites="funder"),
            Column("partner_csr1", "text", note="the PARTNER's CSR-1 registration, when filed"),
            Column("partner_kind", "text", values=('ngo', 'foundation', 'university', 'research', 'government', 'armed_forces', 'hospital', 'network', 'company', 'other')),
            Column("outlay", "numeric", note="INR approved or budgeted for the line, when filed beside the spend"),
            Column("amount", "numeric", note="INR"),
            Column("project_count", "integer", note="set on an aggregate: how many projects the amount covers"),
            Column("is_ongoing", "boolean"),
            Column("start_date", "date", note="kind 'partner': when the grant or partnership began, as a source states it"),
            Column("end_date", "date", note="kind 'partner': when it ended or is due to end"),
            Column("relationship_status", "text", note="kind 'partner': whether it is running, as a source says; NULL means no source said", values=('active', 'concluded', 'unconfirmed', 'dormant')),
            Column("notes", "text"),
            Column("is_public", "boolean", note="false for a line a person marked internal (D14): staff may read it, it is never shown publicly. Every line a writer produces is true"),
            Column("source_key", "text", note="the source registry key, e.g. 'mca_csr'"),
            Column("source_url", "text"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
        ),
        defects=(
            "Sparse: lines arrive one funder at a time from promoted research, so a missing year or kind means 'not recorded', never 'spent nothing' or 'no partners'.",
            "Rows of kind 'programme' are the funder's own programme totals: never sum them with 'spend' lines and never spread them across them; report the two side by side.",
            "domain_tag_id and theme_tag_id are inferences unless classification_confirmed is true, so a total by domain or theme must say whether it is confirmed or includes inferred lines.",
            "Spend lines copied by migration 0031 from the old spend table carry no domain_tag_id. A NULL domain is unclassified, not 'Others' and not absent: never report 'no <domain> spend' for a funder that has spend lines with a NULL domain - say those lines are unclassified.",
            "A 'partner' line is a named relationship. Only when its amount is set does it say money changed hands: the amount (INR) is what the source, usually the recipient's own record, says the partner received from this funder - in that fiscal_year, or, when start_date and end_date span more than one fiscal year, over the whole grant. A partner line with no amount is not evidence of a grant.",
            "A multi-year grant is ONE partner line: the whole grant amount sits on the fiscal_year it started, with start_date and end_date set. Never read it as that year's spend and never divide it across years yourself; say it is a multi-year total.",
            "There is no grants table: grants moved here in 0034 as 'partner' lines with partner_org_id set. Their notes end 'Moved from grants #N by 0034.', which is how a citation of an old grant number is traced.",
            "Partner lines carry no evidence tier column: a line an organisation's own research added says its source type and tier in notes ('From the organisation's research: <source_type>, <tier>.'); a funder's own filing or report says nothing there.",
            "A partner line whose notes say 'fiscal_year is the year the source was read' (or 'the year the row was recorded') had no stated date: it is NOT dated to that fiscal year, so never count it as that year's grant.",
            "Rows with is_public = false are internal: this tool runs as the owner, so row security does not hide them here. Add WHERE is_public to any answer that may be shown publicly, and when an internal row is shown, say it is internal and must not be shown publicly.",
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
            Column("role", "text", note="'priority' is a STATED focus, not evidence of funding - see funder_activity (kind 'footprint' and 'partner') for where a funder actually gave", values=('registered', 'operates', 'funds', 'priority')),
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
        defects=(
            "Themes are tags of kind 'domain', 'theme' or 'sub_theme' (the /resources/taxonomy tree, parent_id upward); kind='csr_sector' (Schedule VII) rows come from CSR filings. A funder's spend and programme lines carry their own domain_tag_id/theme_tag_id in funder_activity, so read both for what it funds. kind='sector' rows are legacy NGO Darpan labels that compare_fit no longer reads. A funder with no rows of a kind has not been researched for it, so a zero overlap from that side is 'not recorded', never 'no focus'.",
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
            Column("intake_mode", "text", note="how an NGO can approach the funder at all, as it says so", values=('open', 'rolling', 'invitation_only', 'rfp_only', 'closed', 'unknown')),
            Column("funds_external", "boolean", note="what the funder SAYS about funding other organisations; funder_activity.implementation_mode is what it did. Report both, never reconcile them"),
            Column("typical_duration_months", "integer", note="a stated typical grant duration"),
            Column("grant_size_min", "numeric", note="a stated grant band, INR: the funder's posture across all its giving, not one call's (that is rfps.amount_min)"),
            Column("grant_size_max", "numeric", note="the top of the stated grant band, INR"),
            Column("cin", "text", note="Corporate Identity Number of a company funder, 21 characters; a trust or society has none. One CIN, one row"),
            Column("aliases", "text[]", note="other names the funder files or is reported under; match names against these too"),
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
        description="Place hierarchy: country > state > district, with every Indian state and district from the Local Government Directory. Self-referencing via parent_id. One region row, 'Northeast India', is a label: the states are not parented to it.",
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
        foreign_keys=(ForeignKey("org_id", "orgs.id"), ForeignKey("funder_id", "funders.id"), ForeignKey("program_id", "programs.id"), ForeignKey("activity_id", "funder_activity.id"), ForeignKey("location_id", "locations.id"), ForeignKey("document_id", "documents.id")),
        columns=(
            Column("id", "bigint"),
            Column("org_id", "bigint", cites="org"),
            Column("funder_id", "bigint", cites="funder"),
            Column("program_id", "bigint"),
            Column("activity_id", "bigint", cites="activity", note="the funder_activity line (usually a partner line, i.e. a grant) this figure reports on"),
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
            *_TIER,
        ),
        defects=(
            _TIER_DEFECT,
            "Sparse: figures arrive from promoted research and are mostly self-reported — check `method` before quoting one as evidence. outcomes of the grants moved in 0034 sit as text in funder_activity.notes; a zero here is not evidence an organisation measures nothing.",
        ),
    ),
    Table(
        name="news_mentions",
        description="GDELT news hits. Rarely linked to an entity — read the caveat.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("activity_id", "funder_activity.id"), ForeignKey("org_id", "orgs.id")),
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
            Column("activity_id", "bigint", cites="activity", note="the funder_activity line a story is about"),
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
            "org_id, funder_id and activity_id are NULL for all 118 rows. Any JOIN or filter on them returns zero rows. A zero result here means 'not linked in the data', NEVER 'no news exists'.",
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
            Column("foreign_unspent", "numeric", note="INR: foreign contribution left unutilised at year end, from the FCRA return"),
            *_TIER,
        ),
        defects=(
            _TIER_DEFECT,
            "Table is empty (0 rows): no accounts have been loaded, so income and spend questions cannot be answered and eligibility gates on revenue cannot be evaluated.",
        ),
    ),
    Table(
        name="org_identifiers",
        description="Statutory registrations of an org (PAN, 12A, 80G, FCRA, Darpan...), one row each, with a status. A row may have no number yet (an application).",
        primary_key=('id',),
        foreign_keys=(ForeignKey("org_id", "orgs.id"), ForeignKey("evidence_document_id", "documents.id")),
        columns=(
            Column("id", "bigint"),
            Column("org_id", "bigint", cites="org"),
            Column("id_type", "text", values=('pan', '12a', '80g', 'fcra', 'csr1', 'darpan', 'cin', 'reg_no')),
            Column("id_value", "text", note="NULL while only applied for: see status and application_ref"),
            Column("verified", "boolean", note="legacy flag from the seed; read status instead"),
            Column("source_url", "text"),
            Column("is_current", "boolean", note="false = superseded, e.g. an old 12A after re-registration"),
            Column("source_name", "text"),
            Column("fetched_at", "timestamp with time zone"),
            Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
            Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
            Column("archive_url", "text"),
            Column("is_public", "boolean", note="false means the number is on file but not published"),
            Column("notes", "text"),
            *_TIER,
            Column("status", "text", note="'applied' is NOT a registration; 'check_blocked' means nobody could read the registry, NEVER that it is valid; 'not_found' means a working source did not list it", values=('applied', 'provisional', 'registered', 'expired', 'suspended', 'cancelled', 'surrendered', 'not_available', 'not_found', 'check_blocked')),
            Column("valid_from", "date"),
            Column("valid_until", "date", note="an FCRA or 12AB/80G approval's end date, when stated"),
            Column("checked_at", "timestamp with time zone", note="when a person or a registry read last confirmed the status"),
            Column("check_method", "text", note="manual_check = a staff member checked by hand; checked_at is when, and it may sit on a registry-tier row", values=('document', 'registry', 'manual_check', 'aggregator')),
            Column("evidence_document_id", "bigint", note="the documents row holding the certificate, order or check evidence"),
            Column("application_ref", "text", note="e.g. a Form 10AB acknowledgement number"),
        ),
        defects=(
            (
                "Only a row with status IN ('registered', 'provisional'), an id_value and is_current is a current "
                "registration. "
                "'applied' is an application, 'check_blocked' means the registry could not be read (never "
                "'valid'), and 'not_found' means a working source did not list it. Filter on status, never on "
                "the row existing."
            ),
            _TIER_DEFECT,
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
            *_TIER,
        ),
        defects=(_TIER_DEFECT,),
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
        defects=(
            "Themes are tags of kind 'domain', 'theme' or 'sub_theme' (the /resources/taxonomy tree, parent_id upward), plus 'population'; programme tags are in program_tags. A sub_theme reaches its Schedule VII clauses through tag_links (linked tag kind 'csr_sector'). kind='sector' rows are legacy NGO Darpan labels that compare_fit no longer reads. An org with no rows is untagged, so a zero overlap from its side is 'not recorded', never 'no focus'.",
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
            Column("website", "text", note="the organisation's own site"),
            Column("description", "text", note="a few sentences in the organisation's own words; claimed unless a document states it"),
            Column("aliases", "text[]", note="every other spelling a source used: short names, filings, directories. Match names against these too"),
            Column("staff_count", "integer", note="people employed, as the source states; staff_count_note says what was counted and where"),
            Column("staff_count_note", "text", note="e.g. '20+ full-time professionals (team page)'. Differing counts across sources are reported as conflicts, not averaged"),
            *_TIER,
        ),
        defects=(
            _TIER_DEFECT,
            (
                "source_url is the NGO Darpan portal's SEARCH page, not a per-organisation record: "
                "11 rows share 4 URLs. Treat it as where the row was looked up, NOT as evidence for "
                "any particular field, and never cite it as the organisation's own page."
            ),
            (
                "fetched_at is NULL on 8 of 11 rows, so the freshness rule cannot fire for them. "
                "Say the date is not recorded rather than implying the data is current."
            ),
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
            *_TIER,
        ),
        defects=(_TIER_DEFECT,),
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
        name="tag_links",
        description="Cross-references between two tags: a sub_theme's SDGs, Schedule VII clause and schemes; a lens's SDG.",
        primary_key=('tag_id', 'linked_tag_id'),
        foreign_keys=(ForeignKey("tag_id", "tags.id"), ForeignKey("linked_tag_id", "tags.id")),
        columns=(
            Column("tag_id", "bigint", note="the sub_theme or lens"),
            Column("linked_tag_id", "bigint", note="what it points at; that tag's kind says what the link means (sdg, csr_sector, scheme)"),
            Column("note", "text", note="for a csr_sector link, the MCA sector name(s) under the clause"),
        ),
    ),
    Table(
        name="tags",
        description="The controlled vocabulary: sectors, populations, Schedule VII, and the domain -> theme -> sub_theme taxonomy.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("parent_id", "tags.id"),),
        columns=(
            Column("id", "bigint"),
            Column("slug", "text"),
            Column("label", "text", note="the human-readable tag, e.g. 'Education'. Profile it before filtering"),
            Column("kind", "text", values=('sdg', 'sector', 'population', 'darpan_sector', 'theme', 'domain', 'cell', 'csr_sector', 'scheme', 'sub_theme', 'lens')),
            Column("parent_id", "bigint", note="the taxonomy tree: a sub_theme's parent is its theme, a theme's is its domain"),
            Column("taxonomy_ref", "text"),
            Column("domain", "text", note="'livelihoods' | 'health' | 'education' | 'environment' | 'others'; required for kind 'domain' and 'cell'"),
            Column("code", "text"),
            Column("level", "text"),
            Column("description", "text"),
            Column("meta", "jsonb", note="crosswalk: sdgs, sectors, maps_to, refs"),
            Column("status", "text", note="'deprecated' rows are kept so old links resolve - exclude them from vocabularies", values=('draft', 'active', 'deprecated')),
            Column("replaced_by", "bigint"),
            Column("sort_order", "integer"),
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

# The three provenance roles the SQL tools surface, and the column each is normally stored in.
# Twenty-one of the catalogued tables carry this set; the rest are join tables, Sangam's own
# rubric output, or reference data, and have no external source to point at.
PROVENANCE_ROLES: tuple[str, ...] = ("url", "name", "fetched")

_ROLE_COLUMNS: Mapping[str, str] = MappingProxyType(
    {"url": "source_url", "name": "source_name", "fetched": "fetched_at"}
)

# One table names its link differently. Spelled out rather than left to miss silently:
# news_mentions.url predates the source_url convention and is the link all the same.
_ROLE_ALIASES: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {"news_mentions": MappingProxyType({"url": "url"})}
)


def _provenance_of(table: Table) -> Mapping[str, str]:
    names = {c.name for c in table.columns}
    aliases = _ROLE_ALIASES.get(table.name, {})
    found: dict[str, str] = {}
    for role in PROVENANCE_ROLES:
        column = aliases.get(role, _ROLE_COLUMNS[role])
        if column in names:
            found[role] = column
    # A source name or a date with no link cites nothing a reader can open.
    return MappingProxyType(found) if "url" in found else MappingProxyType({})


# table -> {role: column}. Derived, never hand-listed, so a table added to the catalog with the
# provenance columns the conventions require gets its sources surfaced without a second edit.
PROVENANCE_COLUMNS: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {name: cols for name, t in CATALOG.items() if (cols := _provenance_of(t))}
)

# Tables that exist in the database and are deliberately NOT in the catalog. Named so verify_against_db()
# can stay quiet about them while still reporting a genuinely new table that nobody has made a decision.
KNOWN_EXCLUDED: frozenset[str] = frozenset(
    {
        # Import's save log: who saved what, and each catalog row's before and after, for undo.
        "promotions",
        "catalog_writes",
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
        # One organisation's Doc Vault findings, quoting its private files.
        "vault_research",
        # Funder Match's saved runs, private to each org; served by /api/funder-matches, read by the page.
        "funder_matches",
        "funder_match_details",
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
            if column.cites and column.cites not in {"org", "funder", "activity", "score"}:
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
