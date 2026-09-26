"""Turn a Postgres error into something the model can act on.

The retry loop already exists — deepagents feeds a tool's returned string back
to the model — so the only question is whether the string carries enough to
converge. Two rules, both learned the hard way:

  * **Echo the SQL that actually ran.** The model sent one string and the
    executor ran the regenerated one. Without the echo it diffs against text
    that never existed and re-sends the same mistake.
  * **Never surface the driver's connection errors verbatim.** psycopg puts the
    DSN — host, user, sometimes more — into OperationalError. That must not
    reach a model provider or a chat transcript.

Duck-typed on `.sqlstate` and `.diag` so it can be unit-tested with a fake
exception and no database.
"""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from typing import Any

from app.agent.tools.sql.catalog import COLUMNS, TABLE_NAMES

MAX_MESSAGE_CHARS = 1_500
_CARET_WINDOW = 40

# Failure prefixes. The retry-limiter middleware counts tool results starting
# with these, so they are a wire format, not just wording.
REJECTED_PREFIX = "db_query rejected:"
FAILED_PREFIX = "db_query failed:"


def _columns_of(table: str) -> str:
    return ", ".join(sorted(COLUMNS[table]))


def _diag(exc: Any, field: str) -> str:
    diag = getattr(exc, "diag", None)
    return (getattr(diag, field, None) or "") if diag is not None else ""


def _primary(exc: Any) -> str:
    return _diag(exc, "message_primary") or str(exc).splitlines()[0]


def _caret(sql: str, position: str) -> str:
    """A window of the executed SQL with a caret under the reported position."""
    try:
        index = int(position) - 1
    except (TypeError, ValueError):
        return ""
    start = max(0, index - _CARET_WINDOW)
    end = min(len(sql), index + _CARET_WINDOW)
    return f"  {sql[start:end]}\n  {' ' * (index - start)}^"


def explain_db_error(exc: Exception, *, executed_sql: str, tables: Sequence[str]) -> str:
    """A model-facing explanation of a failed execution, ending in a next step."""
    if _is_connection_error(exc):
        # Deliberately generic: the driver's text can contain the DSN.
        return (
            f"{FAILED_PREFIX} the database is unreachable right now. "
            "This is not a problem with your SQL. Tell the user the data could not be "
            "reached and do not retry."
        )

    sqlstate = getattr(exc, "sqlstate", None) or ""
    primary = _primary(exc)
    hint = _diag(exc, "message_hint")
    known = [t for t in tables if t in TABLE_NAMES]
    listing = " ".join(f"Columns of {t}: {_columns_of(t)}." for t in sorted(known))

    parts = [f"{FAILED_PREFIX} Postgres {sqlstate or 'error'}.", f"  {primary}"]
    if hint:
        parts.append(f"  HINT: {hint}")

    guidance, include_columns = _guidance(sqlstate, exc, executed_sql, known)
    parts.append(f"executed: {executed_sql}")
    if include_columns and listing:
        parts.append(listing)
    parts.append(guidance)

    message = "\n".join(parts)
    if len(message) > MAX_MESSAGE_CHARS:
        message = message[: MAX_MESSAGE_CHARS - 1] + "…"
    return message


def _guidance(sqlstate: str, exc: Any, executed_sql: str, tables: Sequence[str]) -> tuple[str, bool]:
    """(next step, whether to print the column listing)."""
    if sqlstate == "42703":  # undefined_column
        return ("Next: fix the column name and call db_query again.", True)

    if sqlstate == "42P01":  # undefined_table
        near = difflib.get_close_matches(_primary(exc).lower(), sorted(TABLE_NAMES), n=3)
        suffix = f" Did you mean: {', '.join(near)}?" if near else ""
        return (f"Next: call db_list_tables for the readable tables.{suffix}", False)

    if sqlstate == "42883":  # undefined_function
        return ("Next: use a standard SQL function instead, then call db_query again.", False)

    if sqlstate == "42601":  # syntax_error
        caret = _caret(executed_sql, _diag(exc, "message_detail") or getattr(exc, "position", ""))
        return ((f"{caret}\n" if caret else "") + "Next: fix the syntax and call db_query again.", False)

    if sqlstate == "42803":  # grouping_error
        return (
            (
                "Next: every selected column must be in GROUP BY or inside an aggregate. "
                "If the ungrouped column is an id you added for citations, either group by "
                "it too or wrap it in min()."
            ),
            True,
        )

    if sqlstate == "57014":  # query_canceled
        return (
            (
                "Next: the query exceeded its time limit. Narrow the WHERE clause, use a "
                "smaller LIMIT, or aggregate instead of listing rows."
            ),
            False,
        )

    if sqlstate in {"22P02", "22003"}:  # invalid_text_representation / numeric_out_of_range
        return (
            (
                "Next: a literal does not match its column's type. Check the types with "
                "db_describe_table, and use db_profile_column to see how values are stored."
            ),
            True,
        )

    if sqlstate == "42501":  # insufficient_privilege
        return (
            (
                "Next: that table or column is not readable by this tool. "
                "Call db_list_tables to see what is."
            ),
            False,
        )

    if sqlstate == "25006":  # read_only_sql_transaction
        # Unreachable: the validator rejects writes. If seen, it has a hole.
        return (
            "Next: only SELECT is possible here. Rewrite the query as a read.",
            False,
        )

    return ("Next: read the error above, fix the SQL, and call db_query again.", True)


def _is_connection_error(exc: Exception) -> bool:
    """True when the server never answered, so the text may carry the DSN.

    Tested by presence of a SQLSTATE, not by exception class name. A server-side
    SQL error always carries one. Everything without one — psycopg's
    OperationalError and PoolTimeout, asyncio.TimeoutError, ConnectionRefusedError,
    a bare OSError — came from the driver or the network, and any of those can
    render the host and user we connected with. Matching on class names would
    have to enumerate that list correctly forever; this asks the question that
    actually matters and fails safe for anything unanticipated.
    """
    return getattr(exc, "sqlstate", None) is None
