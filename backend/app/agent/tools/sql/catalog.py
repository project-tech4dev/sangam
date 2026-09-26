"""The tables and columns the SQL tool may read — the allowlist, as data.

This is a security control, so it is Python rather than YAML: it shows up in a
diff, it is type-checked, pure unit tests can import it with no database and no
parse step, and nothing can hot-reload it.

Three rules keep it honest:

  * A column that is not listed here does not exist as far as the tool is
    concerned. There is no second denylist to keep in sync — `contacts.email`
    is absent, so it fails as "unknown column" through the same code path as a
    typo, and the reader role's column-level GRANT enforces the same line
    server-side.
  * `defects` are evidence-backed caveats about the DATA, not the schema. They
    are injected into every result that touches the table, because a model that
    cannot see them reports "0 rows" as "none exist". Delete a line here when a
    migration fixes the underlying data — that is the seam between this work and
    the schema review.
  * `verify_against_db()` runs at boot and fails loudly on drift. A catalog that
    disagrees with the database produces confidently wrong answers, which is
    worse than not starting.

This module holds no logic beyond the import-time self-check and that verify.
Everything that reasons about the catalog lives in validator.py.
"""

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
            Column("role", "text", values=('registered', 'operates', 'funds')),
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
        ),
    ),
    Table(
        name="grants",
        description="Researched funding relationships: who funded whom, when, how much.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("org_id", "orgs.id"), ForeignKey("program_id", "programs.id")),
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
        ),
    ),
    Table(
        name="locations",
        description="Place hierarchy: country > state > district. Self-referencing via parent_id.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("parent_id", "locations.id"),),
        columns=(
            Column("id", "bigint"),
            Column("kind", "text", values=('country', 'region', 'state', 'district', 'block')),
            Column("name", "text", note="stored UPPER CASE, e.g. 'DIMAPUR'. Compare case-insensitively (ILIKE)"),
            Column("parent_id", "bigint", note="-> locations.id. district -> state -> country"),
        ),
        defects=(
            "All 10 districts currently parent to Assam (id=2), including DIMAPUR (really Nagaland) and BISHNUPUR and TAMENGLONG (really Manipur). Any state-level rollup through parent_id is wrong for those three. Say so when a question depends on state.",
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
        ),
        defects=(
            "org_id, funder_id and grant_id are NULL for all 118 rows. Any JOIN or filter on them returns zero rows. A zero result here means 'not linked in the data', NEVER 'no news exists'.",
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
        ),
        defects=(
            "Table is empty (0 rows): no programme has been tagged, so an INNER JOIN from programs through this table silently returns nothing. Outer-join it, or read programs directly.",
        ),
    ),
    Table(
        name="programs",
        description="A programme run by an org, or a funding programme run by a funder — exactly one owner.",
        primary_key=('id',),
        foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("org_id", "orgs.id")),
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
            Column("kind", "text", values=('sector', 'population', 'theme')),
            Column("parent_id", "bigint"),
            Column("taxonomy_ref", "text"),
        ),
    ),
)

CATALOG: Mapping[str, Table] = MappingProxyType({t.name: t for t in _TABLES})

TABLE_NAMES: frozenset[str] = frozenset(CATALOG)

COLUMNS: Mapping[str, Mapping[str, Column]] = MappingProxyType(
    {name: MappingProxyType({c.name: c for c in t.columns}) for name, t in CATALOG.items()}
)

# What sqlglot's qualify() needs: EVERY column, including heavy ones. A reduced
# schema here would make a heavy column unresolvable when asked for by name,
# which is not the intent — `*` should omit them, naming one should work. The
# trimming of `*` happens after qualify, against STAR_COLUMNS.
SQLGLOT_SCHEMA: dict[str, dict[str, str]] = {
    name: {c.name: c.type for c in t.columns} for name, t in CATALOG.items()
}

STAR_COLUMNS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {name: tuple(c.name for c in t.columns if not c.heavy) for name, t in CATALOG.items()}
)

# (table, column) -> citation kind. Set on primary keys AND on every foreign key
# pointing at one, so a row from programs or contacts is citable through the
# org_id/funder_id it already carries.
CITE_COLUMNS: Mapping[tuple[str, str], str] = MappingProxyType(
    {(name, c.name): c.cites for name, t in CATALOG.items() for c in t.columns if c.cites}
)

DEFECTS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {name: t.defects for name, t in CATALOG.items() if t.defects}
)

# Tables that exist in the database and are deliberately NOT in the catalog.
# Named so verify_against_db() can stay quiet about them while still reporting a
# genuinely new table that nobody has made a decision about.
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
        # Infrastructure.
        "schema_migrations",
        "graph_ingest_log",
    }
)


def _self_check() -> None:
    """Fail at import if the catalog contradicts itself.

    Cheap, and it turns a typo in a column name from a confusing runtime
    rejection ("unknown column id") into an ImportError naming the table.
    """
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
    """Problems found comparing the catalog to the live schema; empty when clean.

    Names only. Types are deliberately not compared: information_schema reports
    vector(1536) as USER-DEFINED and text[] as ARRAY, so a type check would
    produce false drift on exactly the columns that are hardest to reason about.

    Uses conn.execute directly rather than traced_fetch: this runs once at boot,
    and importing the tracing module here would pull copilotkit and ag_ui into
    the dependency graph of every pure catalog unit test.
    """
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
    """Live tables that are neither in the catalog nor knowingly excluded.

    Not an error — a new table should be invisible to the agent until someone
    decides it is safe — but it is logged at boot so the decision gets made.
    """
    return sorted(live_table_names - TABLE_NAMES - KNOWN_EXCLUDED)
