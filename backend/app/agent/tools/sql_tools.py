"""The agent's SQL tools: discover the schema, then query it."""

from __future__ import annotations

from langchain_core.tools import tool

from app.agent.tools.sql import render
from app.agent.tools.sql.catalog import CATALOG, COLUMNS, DEFECTS, TABLE_NAMES
from app.agent.tools.sql.errors import FAILED_PREFIX, REJECTED_PREFIX, explain_db_error
from app.agent.tools.sql.executor import PsycopgExecutor, ReaderRoleMissing
from app.agent.tools.sql.validator import SqlRejected, ValidatedQuery, validate
from app.core.config import get_settings

MAX_PROFILE_VALUES = 20


def _executor() -> PsycopgExecutor:
    settings = get_settings()
    return PsycopgExecutor(
        timeout_ms=settings.sql_timeout_ms,
        reader_role=settings.sql_reader_role,
    )


def _caveats_for(tables) -> str:
    seen: list[str] = []
    for table in tables:
        seen.extend(DEFECTS.get(table, ()))
    return render.render_caveats(seen)


@tool
async def db_list_tables() -> str:
    """List every database table the SQL tools may read, with a one-line description.

    Start here for any question about the data. Then db_describe_table for the
    tables that look relevant, db_profile_column before filtering on a text
    column, and db_query to run the SELECT.
    """
    try:
        lines = [f"{len(CATALOG)} tables are readable:"]
        lines += [f"  {name} — {table.description}" for name, table in sorted(CATALOG.items())]
        lines.append(
            "\nCall db_describe_table before writing SQL against a table, and "
            "db_profile_column before filtering on a text column."
        )
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 - error-as-string tool discipline
        return f"db_list_tables failed: {exc}"


@tool
async def db_describe_table(tables: str) -> str:
    """Show a table's columns, types, allowed values, relationships and known data problems.

    Args:
        tables: one or more table names, comma-separated (e.g. "grants,funders").

    Call this before writing SQL against a table you have not queried this turn,
    and again whenever db_query reports an unknown column. Relationships are
    listed in both directions, so you can see what joins to what without guessing.
    """
    try:
        wanted = [t.strip().lower() for t in tables.split(",") if t.strip()]
        if not wanted:
            return "db_describe_table needs at least one table name."

        blocks: list[str] = []
        for name in wanted:
            if name not in CATALOG:
                blocks.append(f"{name}: unknown table. Call db_list_tables for the readable ones.")
                continue
            table = CATALOG[name]
            block = [f"{name} — {table.description}", f"  primary key: {', '.join(table.primary_key)}"]
            for column in table.columns:
                bits = [f"  {column.name} ({column.type})"]
                if column.values:
                    bits.append(f"one of: {', '.join(column.values)}")
                if column.note:
                    bits.append(column.note)
                if column.heavy:
                    bits.append("large; omitted from SELECT * but selectable by name")
                block.append(" — ".join(bits))
            for fk in table.foreign_keys:
                block.append(f"  {name}.{fk.column} -> {fk.references}")
            # The reverse direction is what lets a join be written without guessing.
            for other_name, other in sorted(CATALOG.items()):
                for fk in other.foreign_keys:
                    if fk.references.split(".")[0] == name:
                        block.append(f"  referenced by {other_name}.{fk.column}")
            for defect in table.defects:
                block.append(f"  CAVEAT: {defect}")
            blocks.append("\n".join(block))
        return "\n\n".join(blocks)
    except Exception as exc:  # noqa: BLE001 - error-as-string tool discipline
        return f"db_describe_table failed: {exc}"


@tool
async def db_profile_column(table: str, column: str) -> str:
    """Show a column's most common values, with counts.

    ALWAYS use this before filtering on a text column. What a user says and what
    the column stores are often different: legal_form holds 'Public Charitable
    Trust' rather than 'Trust', and locations.name is stored upper-case
    ('DIMAPUR'). Filtering on the wrong spelling returns zero rows, which reads
    like an answer and is not one.

    Args:
        table: the table name.
        column: the column to profile.
    """
    try:
        table, column = table.strip().lower(), column.strip().lower()
        if table not in TABLE_NAMES:
            return (
                f"{REJECTED_PREFIX} unknown table {table!r}. Call db_list_tables for the "
                "readable ones."
            )
        if column not in COLUMNS[table]:
            return (
                f"{REJECTED_PREFIX} {table} has no readable column {column!r}. "
                f"Columns of {table}: {', '.join(sorted(COLUMNS[table]))}."
            )

        # Server-constructed, but still routed through validate() so it inherits the same limit clamp and
        # regeneration as anything else, and through the executor so it inherits the read-only transaction.
        query = validate(
            f"SELECT {column} AS value, count(*) AS n FROM {table} "
            f"GROUP BY {column} ORDER BY n DESC, {column} LIMIT {MAX_PROFILE_VALUES}",
            max_rows=MAX_PROFILE_VALUES,
        )
        rows = await _executor().run(query)
        if not rows:
            return f"{table}.{column} has no rows to profile (the table is empty)."

        lines = [f"{table}.{column} — {len(rows)} most common value(s), as stored:"]
        lines += [f"  {render.render_cell(r['value'])}  ({r['n']})" for r in rows]
        caveats = _caveats_for([table])
        if caveats:
            lines.append(caveats)
        return "\n".join(lines)
    except ReaderRoleMissing as exc:
        return f"{FAILED_PREFIX} {exc}"
    except Exception as exc:  # noqa: BLE001 - error-as-string tool discipline
        return f"db_profile_column failed: {exc}"


@tool
async def db_query(sql: str, purpose: str) -> str:
    """Run ONE read-only SELECT and return the rows.

    Args:
        sql: a single PostgreSQL SELECT (WITH, UNION, INTERSECT and EXCEPT are
            allowed). No semicolons, no writes. Only the tables from
            db_list_tables exist. Project the entity's id column (e.g. orgs.id)
            so the rows can be cited.
        purpose: one short sentence on what you are trying to learn. Recorded on
            the trace; it does not change the query.

    A row limit is applied automatically and SELECT * omits large JSONB columns.
    If the query is rejected or fails, the reply names the exact problem and the
    next step — read it, fix the SQL, and call again.
    """
    del purpose  # recorded via the tool call itself; not used to build the query
    query: ValidatedQuery | None = None
    try:
        query = validate(sql, max_rows=get_settings().sql_max_rows)
    except SqlRejected as exc:
        return f"{REJECTED_PREFIX} {exc}"
    except Exception as exc:  # noqa: BLE001 - error-as-string tool discipline
        return f"{REJECTED_PREFIX} the query could not be checked ({exc})."

    try:
        rows = await _executor().run(query)
    except ReaderRoleMissing as exc:
        return f"{FAILED_PREFIX} {exc}"
    except Exception as exc:  # noqa: BLE001 - error-as-string tool discipline
        return explain_db_error(exc, executed_sql=query.sql, tables=query.tables)

    truncated = len(rows) > query.limit
    body = render.render_rows(
        rows[: query.limit],
        citations=query.citations,
        limit=query.limit,
        truncated=truncated,
    )

    header = [f"{len(rows[: query.limit])} row(s)."]
    if query.rewrites:
        header.append("adjusted: " + "; ".join(query.rewrites) + ".")
    caveats = _caveats_for(query.tables)
    if caveats:
        header.append(caveats)
    return "\n".join([*header, f"executed: {query.sql}", body])
