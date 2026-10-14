"""Validate model-written SQL before it may reach Postgres."""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import build_scope

from app.agent.tools.sql.catalog import (
    CITE_COLUMNS,
    COLUMNS,
    PROVENANCE_COLUMNS,
    PROVENANCE_ROLES,
    SQLGLOT_SCHEMA,
    STAR_COLUMNS,
    TABLE_NAMES,
)

# sqlglot logs a WARNING to the root logger for every statement it cannot model ("RESET ROLE contains
# unsupported syntax. Falling back to parsing as a 'Command'"). That fires on exactly the inputs we reject.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

DEFAULT_MAX_ROWS = 50
HARD_MAX_ROWS = 200

# Parser-DoS guard, checked before parse. Deeply nested SQL can blow the stack;
# a legitimate query against 28 tables is nowhere near this.
MAX_SQL_CHARS = 8_000

DIALECT = "postgres"

# Output names the validator appends for itself. Reserved rather than merely unlikely: a
# projection aliased into this namespace would be read back as a source, so it is rejected.
PROVENANCE_PREFIX = "__prov__"

# Statements that write or change state, wherever they appear in the tree — a DELETE inside a CTE is still a
# DELETE. Verified present in sqlglot 27.x; note COPY/TRUNCATE/GRANT are their own node types, NOT.
_WRITE_NODE_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Create",
    "Drop",
    "Alter",
    "TruncateTable",
    "Copy",
    "Grant",
    "Set",
    "Transaction",
    "Commit",
    "Rollback",
    # sqlglot's fallback for verb-first statements it does not model (VACUUM,
    # CALL, ...). Reaching one inside a query means something is very wrong.
    "Command",
)


def _nodes(*names: str) -> tuple[type[exp.Expression], ...]:
    """Resolve node classes by name, failing LOUDLY if one has gone."""
    missing = [n for n in names if not hasattr(exp, n)]
    if missing:
        raise ImportError(
            f"sqlglot {sqlglot.__version__} has no expression class(es) {', '.join(missing)}; "
            "the SQL validator's node lists need updating for this version"
        )
    return tuple(getattr(exp, n) for n in names)


_WRITE_NODES = _nodes(*_WRITE_NODE_NAMES)

# Non-standard functions the model may call. An allowlist rather than a denylist because the connecting role
# is a superuser until the reader role lands, and `SELECT pg_read_file('/etc/passwd')` is a perfectly valid.
ALLOWED_FUNCTIONS = frozenset(
    {
        "similarity",  # pg_trgm, used by the curated tools for fuzzy name match
        "word_similarity",
        "unaccent",
        "age",
        "cardinality",
        "jsonb_agg",
        "jsonb_array_length",
        "jsonb_extract_path_text",
        "jsonb_object_keys",
    }
)

# Typed nodes that bypass the exp.Anonymous allowlist entirely and must be named.
_DENIED_NODES = _nodes(
    "CurrentUser",  # session identity
    "GenerateSeries",  # row generators: unbounded result, ignores the LIMIT clamp
    "Unnest",
)

_CATALOG_SCHEMAS = {"pg_catalog", "information_schema"}
_CATALOG_CAST_TYPES = {"regclass", "regproc", "regnamespace", "oid"}


class SqlRejected(Exception):
    """A rejection written for the model. The message IS the interface."""


@dataclass(frozen=True, slots=True)
class CitationPlan:
    """A result column whose value yields a citation marker."""

    output_column: str
    kind: str


@dataclass(frozen=True, slots=True)
class ProvenancePlan:
    """A result column carrying where one of the query's tables got its rows."""

    output_column: str
    table: str
    role: str
    """One of catalog.PROVENANCE_ROLES: 'url' | 'name' | 'fetched'."""


@dataclass(frozen=True, slots=True)
class ValidatedQuery:
    sql: str
    """The regenerated statement. This, and only this, is what executes."""
    tables: tuple[str, ...]
    limit: int
    citations: tuple[CitationPlan, ...] = ()
    rewrites: tuple[str, ...] = ()
    """What validation changed, told to the model so it can learn the shape."""
    aggregate: bool = False
    provenance: tuple[ProvenancePlan, ...] = ()
    provenance_skipped: str | None = None
    """Why the rows carry no source, when they do not. Shown instead of nothing."""


def _reject(message: str) -> None:
    raise SqlRejected(message)


def _columns_of(table: str) -> str:
    return ", ".join(sorted(COLUMNS[table]))


def _did_you_mean(name: str, options) -> str:
    near = difflib.get_close_matches(name.lower(), sorted(options), n=3)
    return f" Did you mean: {', '.join(near)}?" if near else ""


def validate(
    sql: str,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    dialect: str = DIALECT,
) -> ValidatedQuery:
    """Return a safe, regenerated statement, or raise SqlRejected explaining why not."""
    max_rows = min(max(int(max_rows), 1), HARD_MAX_ROWS)
    rewrites: list[str] = []

    root = _parse_single_query(sql, dialect)
    _reject_writes(root)
    _reject_disallowed_clauses(root)
    cte_names = _check_tables(root)
    _check_functions(root)

    had_star = _has_star_projection(root)
    qualified = _qualify(root, root_tables=_referenced_tables(root, cte_names), dialect=dialect)
    _recheck_columns(qualified)
    _reject_whole_row_references(qualified)
    _reject_reserved_aliases(qualified)
    if had_star:
        _trim_expanded_star(qualified, rewrites)
    _dedupe_output_names(qualified, rewrites)

    aggregate = _is_aggregate(qualified)
    # After deduping (the reserved prefix cannot collide with a renamed column) and before the
    # limit, which does not touch the projection list.
    provenance, provenance_skipped = _plan_provenance(qualified, aggregate=aggregate)
    limit = _apply_limit(qualified, max_rows, rewrites)
    citations = _plan_citations(qualified)

    return ValidatedQuery(
        sql=qualified.sql(dialect=dialect, comments=False),
        tables=tuple(sorted(_referenced_tables(root, cte_names))),
        limit=limit,
        citations=tuple(citations),
        rewrites=tuple(rewrites),
        aggregate=aggregate,
        provenance=tuple(provenance),
        provenance_skipped=provenance_skipped,
    )


def _parse_single_query(sql: str, dialect: str) -> exp.Query:
    if len(sql) > MAX_SQL_CHARS:
        _reject(
            f"the query is {len(sql)} characters, over the {MAX_SQL_CHARS} limit. "
            "Aggregate in SQL rather than listing every case."
        )
    try:
        statements = [s for s in sqlglot.parse(sql, dialect=dialect) if s is not None]
    except (ParseError, RecursionError) as exc:
        hint = ""
        if "%" in sql:
            hint = " If you meant pg_trgm fuzzy matching, use similarity(a, b) > 0.3."
        _reject(f"could not parse this as {dialect} SQL: {exc}.{hint}")

    if len(statements) != 1:
        _reject(
            f"{len(statements)} statements found; send exactly one SELECT. "
            "Semicolon-separated statements are not allowed."
        )

    root = statements[0]
    while isinstance(root, exp.Subquery) and root.this is not None:
        root = root.this

    # Positive check: anything that is not a query is rejected by construction,
    # including statements sqlglot models as Copy/TruncateTable/Alias.
    if not isinstance(root, exp.Query):
        _reject(
            f"only SELECT is allowed (optionally with WITH, UNION, INTERSECT or EXCEPT); "
            f"this parsed as {type(root).__name__.upper()}."
        )
    return root


def _reject_writes(root: exp.Query) -> None:
    """A Query can still contain a write: WITH x AS (DELETE ... RETURNING *) SELECT."""
    found = next(root.find_all(*_WRITE_NODES), None)
    if found is not None:
        _reject(
            f"this statement writes or changes state (found {found.key.upper()}); "
            "only read-only SELECT is allowed."
        )


def _reject_disallowed_clauses(root: exp.Query) -> None:
    if root.args.get("into"):
        _reject("SELECT ... INTO creates a table. Remove the INTO clause.")
    if root.args.get("locks"):
        _reject("locking clauses (FOR UPDATE / FOR SHARE) take row locks and are not allowed.")
    with_ = root.args.get("with")
    if with_ is not None and with_.args.get("recursive"):
        _reject(
            "WITH RECURSIVE is not allowed: Postgres materialises it, so the row limit "
            "cannot stop a runaway. The locations hierarchy is only two levels deep — "
            "self-join locations on parent_id instead."
        )


def _check_tables(root: exp.Query) -> set[str]:
    """Every physical table must be in the catalog. Returns the CTE names."""
    cte_names = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
    shadowed = cte_names & TABLE_NAMES
    if shadowed:
        _reject(
            f"the CTE named {min(shadowed)!r} shadows a real table of the same name, "
            "which makes column checking ambiguous. Rename the CTE."
        )

    for table in root.find_all(exp.Table):
        if table.catalog or (table.db and table.db.lower() not in {"public", ""}):
            _reject(
                f"cross-schema references are not allowed ({table.sql(dialect=DIALECT)}). "
                "System catalogs and other schemas are out of reach; use the listed tables."
            )
        if not isinstance(table.this, exp.Identifier):
            rendered = table.this.sql(dialect=DIALECT) if table.this else "?"
            _reject(
                f"table functions are not allowed in FROM ({rendered}). "
                "Select from one of the listed tables."
            )
        identifier: exp.Identifier = table.this
        name = identifier.name if identifier.quoted else identifier.name.lower()
        if name in cte_names:
            continue
        if name not in TABLE_NAMES:
            extra = ""
            if identifier.quoted and name.lower() in TABLE_NAMES:
                extra = (
                    f' Note that "{name}" is quoted, so it is case-sensitive; '
                    f"write {name.lower()} unquoted."
                )
            _reject(
                f"unknown table {name!r}.{_did_you_mean(name, TABLE_NAMES)}{extra} "
                "Call db_list_tables for the tables you can read."
            )
    return cte_names


def _referenced_tables(root: exp.Query, cte_names: set[str]) -> set[str]:
    names = set()
    for table in root.find_all(exp.Table):
        if isinstance(table.this, exp.Identifier):
            name = table.this.name.lower()
            if name in TABLE_NAMES and name not in cte_names:
                names.add(name)
    return names


def _check_functions(root: exp.Query) -> None:
    for fn in root.find_all(exp.Anonymous):
        name = str(fn.this).lower()
        if name not in ALLOWED_FUNCTIONS:
            _reject(
                f"the function {name}() is not allowed. Beyond the standard SQL functions "
                f"(count, sum, min, max, lower, date_trunc, string_agg, ...), only these are "
                f"available: {', '.join(sorted(ALLOWED_FUNCTIONS))}."
            )

    if next(root.find_all(*_DENIED_NODES), None) is not None:
        _reject(
            "session-identity and row-generating functions (current_user, generate_series, "
            "unnest) are not allowed."
        )

    for dot in root.find_all(exp.Dot):
        parts = {str(dot.this).lower(), str(dot.name).lower()}
        if parts & _CATALOG_SCHEMAS:
            _reject("system catalog references (pg_catalog, information_schema) are not allowed.")

    if next(root.find_all(exp.Placeholder, exp.Parameter), None) is not None:
        _reject(
            "placeholders ($1, %s, ?) are not supported because the query runs with no "
            "parameters. Write literal values directly into the SQL."
        )

    for cast in root.find_all(exp.Cast):
        if cast.to is not None and str(cast.to.this).lower() in _CATALOG_CAST_TYPES:
            _reject("casts to catalog types (regclass, oid, ...) are not allowed.")


def _qualify(root: exp.Query, *, root_tables: set[str], dialect: str) -> exp.Query:
    """Expand `*`, resolve every column, and quote identifiers."""
    try:
        return qualify(
            root.copy(),
            schema=SQLGLOT_SCHEMA,
            dialect=dialect,
            infer_schema=True,
            validate_qualify_columns=True,
            quote_identifiers=True,
            identify=True,
        )
    except OptimizeError as exc:
        _reject(_column_error(str(exc), root_tables))
    except Exception as exc:  # noqa: BLE001 - unknown analyser failure must fail CLOSED
        # qualify() raises different types for different query shapes, and letting one
        # through unvalidated is what must never happen, so anything unrecognised fails.
        _reject(
            f"the query could not be analysed ({type(exc).__name__}: {exc}). "
            "Simplify it — split a complex join into steps — and retry."
        )


def _column_error(message: str, tables: set[str]) -> str:
    """Turn 'Column X could not be resolved' into something the model can act on."""
    listing = " ".join(f"Columns of {t}: {_columns_of(t)}." for t in sorted(tables) if t in COLUMNS)
    hint = ""
    if "sector" in message.lower():
        hint = " Sectors are tags: join org_tags to tags and read tags.label."
    elif "email" in message.lower() or "phone" in message.lower():
        hint = " Personal contact details are not readable by this tool."
    names = ",".join(sorted(tables)) or "the tables you need"
    return (
        f"{message.rstrip('.')}.{hint} {listing} "
        f'Next: call db_describe_table("{names}") and retry.'
    )


def _recheck_columns(qualified: exp.Query) -> None:
    """Conservative second pass over resolved scopes."""
    root_scope = build_scope(qualified)
    if root_scope is None:
        return
    for scope in root_scope.traverse():
        for column in scope.columns:
            source = scope.sources.get(column.table)
            if not isinstance(source, exp.Table):
                continue  # a CTE or derived table; its own scope was checked
            table = source.name.lower()
            if table in COLUMNS and column.name not in COLUMNS[table]:
                _reject(_column_error(f"Column '{column.name}' does not exist on {table}", {table}))


def _reject_whole_row_references(qualified: exp.Query) -> None:
    """A star left after expansion reads the whole row, columns the catalog hides included."""
    for star in qualified.find_all(exp.Star):
        if isinstance(star.parent, exp.Count):
            continue
        _reject(
            "`alias.*` inside an expression reads every column of the row, including ones this "
            "tool cannot read. Name the columns you need instead: count(*) or count(alias.id) "
            "to count rows, array_agg(alias.name) to collect a column."
        )


def _dedupe_output_names(qualified: exp.Query, rewrites: list[str]) -> None:
    """`SELECT o.id, f.id` would collapse to one key under psycopg's dict_row."""
    seen: dict[str, int] = {}
    for projection in qualified.expressions:
        name = projection.alias_or_name
        seen[name] = seen.get(name, 0) + 1
    duplicated = {n for n, count in seen.items() if count > 1}
    if not duplicated:
        return

    used: set[str] = set()
    for projection in qualified.expressions:
        name = projection.alias_or_name
        if name not in duplicated:
            used.add(name)
            continue
        inner = projection.this if isinstance(projection, exp.Alias) else projection
        table = inner.table if isinstance(inner, exp.Column) else ""
        candidate = f"{table}_{name}" if table else f"{name}_1"
        suffix = 2
        while candidate in used or candidate in seen:
            candidate = f"{table}_{name}_{suffix}" if table else f"{name}_{suffix}"
            suffix += 1
        used.add(candidate)
        projection.replace(exp.alias_(inner.copy(), candidate, quoted=True))
        rewrites.append(
            f"more than one column was called {name!r}; the one from "
            f"{table or 'the query'} is returned as {candidate!r}"
        )


def _has_star_projection(root: exp.Query) -> bool:
    """Did the model write `*` or `alias.*` at the top level?"""
    selects = [root] if isinstance(root, exp.Select) else list(root.find_all(exp.Select))
    for select in selects:
        for projection in select.expressions:
            if isinstance(projection, exp.Star):
                return True
            if isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star):
                return True
    return False


def _trim_expanded_star(qualified: exp.Query, rewrites: list[str]) -> None:
    """Drop heavy columns that only appeared because `*` expanded to them."""
    root_scope = build_scope(qualified)
    if root_scope is None:
        return
    alias_to_table = {
        alias: source.name.lower()
        for alias, source in root_scope.sources.items()
        if isinstance(source, exp.Table)
    }

    dropped: list[str] = []
    for projection in list(qualified.expressions):
        inner = projection.this if isinstance(projection, exp.Alias) else projection
        if not isinstance(inner, exp.Column):
            continue
        table = alias_to_table.get(inner.table) or inner.table.lower()
        if table in STAR_COLUMNS and inner.name not in STAR_COLUMNS[table]:
            dropped.append(f"{table}.{inner.name}")
            projection.pop()

    if dropped:
        rewrites.append(
            f"`*` omitted {len(dropped)} large column(s) ({', '.join(sorted(dropped))}); "
            "select them by name if you need them"
        )


def _apply_limit(qualified: exp.Query, max_rows: int, rewrites: list[str]) -> int:
    """Clamp or inject a row limit, then ask for one extra row to detect truncation."""
    existing = qualified.args.get("limit")
    requested: int | None = None

    if isinstance(existing, exp.Fetch):
        count = existing.args.get("count")
        requested = int(count.name) if isinstance(count, exp.Literal) and count.is_int else None
        if requested is None:
            _reject("FETCH FIRST needs a plain integer count.")
    elif existing is not None:
        value = existing.expression
        if not (isinstance(value, exp.Literal) and value.is_int):
            _reject("LIMIT must be a plain integer literal, not an expression or subquery.")
        requested = int(value.name)

    if requested is None:
        effective = max_rows
        rewrites.append(f"no LIMIT was given, so LIMIT {effective} was applied")
    elif requested > max_rows:
        effective = max_rows
        rewrites.append(f"LIMIT {requested} was clamped to {effective}")
    else:
        # A smaller limit expresses intent ("top 5") and is kept.
        effective = requested

    qualified.limit(effective + 1, copy=False)
    return effective


def _plan_citations(qualified: exp.Query) -> list[CitationPlan]:
    """Map each projected column to the citation kind its value yields."""
    root_scope = build_scope(qualified)
    if root_scope is None:
        return []
    alias_to_table = {
        alias: source.name.lower()
        for alias, source in root_scope.sources.items()
        if isinstance(source, exp.Table)
    }

    plans: list[CitationPlan] = []
    for projection in qualified.expressions:
        inner = projection.this if isinstance(projection, exp.Alias) else projection
        if not isinstance(inner, exp.Column):
            continue
        table = alias_to_table.get(inner.table) or inner.table.lower()
        kind = CITE_COLUMNS.get((table, inner.name))
        if kind:
            plans.append(CitationPlan(output_column=projection.alias_or_name, kind=kind))
    return plans


def _is_aggregate(qualified: exp.Query) -> bool:
    if qualified.args.get("group"):
        return True
    return any(
        isinstance(node, exp.AggFunc)
        for projection in qualified.expressions
        for node in projection.walk()
    )


def _reject_reserved_aliases(qualified: exp.Query) -> None:
    """`__prov__…` is the validator's own output namespace, not the model's."""
    for projection in qualified.expressions:
        if projection.alias_or_name.startswith(PROVENANCE_PREFIX):
            _reject(
                f"output names starting with {PROVENANCE_PREFIX!r} are reserved for the "
                "source columns the tool adds for you. Alias that column something else — "
                "sources are reported without being asked for."
            )


def _plan_provenance(
    qualified: exp.Query, *, aggregate: bool
) -> tuple[list[ProvenancePlan], str | None]:
    """Make every row's source reachable, by mapping what is projected then adding what is not.

    Mapping first matters: `source_url` is not heavy, so `SELECT *` expands to it and
    `_trim_expanded_star` keeps it. Appending blindly would put the URL in the row body AND in
    the sources block, and the output budget would pay for it twice.
    """
    if not isinstance(qualified, exp.Select):
        return [], "the query combines results with UNION/INTERSECT/EXCEPT, which carry no single source"
    if aggregate:
        return [], "the rows are aggregated, so they belong to no single source row"
    if qualified.args.get("distinct"):
        return [], "SELECT DISTINCT collapses rows, so a per-row source would be wrong"

    root_scope = build_scope(qualified)
    if root_scope is None:
        return [], None

    # Keyed by ALIAS, not table name: a self-join has two aliases on one table, and one output
    # name for both would collapse under psycopg's dict_row.
    aliases = {
        alias: source.name.lower()
        for alias, source in root_scope.sources.items()
        if isinstance(source, exp.Table) and source.name.lower() in PROVENANCE_COLUMNS
    }
    opaque = sorted(
        alias for alias, source in root_scope.sources.items() if not isinstance(source, exp.Table)
    )

    plans: list[ProvenancePlan] = []
    mapped: set[tuple[str, str]] = set()
    for projection in qualified.expressions:
        inner = projection.this if isinstance(projection, exp.Alias) else projection
        if not isinstance(inner, exp.Column) or inner.table not in aliases:
            continue
        table = aliases[inner.table]
        for role, column in PROVENANCE_COLUMNS[table].items():
            if inner.name == column:
                plans.append(
                    ProvenancePlan(output_column=projection.alias_or_name, table=table, role=role)
                )
                mapped.add((inner.table, role))

    for alias, table in sorted(aliases.items()):
        for role in PROVENANCE_ROLES:
            column = PROVENANCE_COLUMNS[table].get(role)
            if column is None or (alias, role) in mapped:
                continue
            name = f"{PROVENANCE_PREFIX}{alias}__{role}"
            qualified.select(
                exp.alias_(exp.column(column, table=alias, quoted=True), name, quoted=True),
                append=True,
                copy=False,
            )
            plans.append(ProvenancePlan(output_column=name, table=table, role=role))

    skipped = None
    if opaque:
        skipped = (
            f"rows coming through {', '.join(opaque)} carry no source — a CTE or subquery hides "
            "which table row they came from"
        )
    elif not plans:
        skipped = "none of the tables read record a source URL"
    return plans, skipped
