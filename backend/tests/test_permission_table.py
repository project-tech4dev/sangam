"""ARCHITECTURE §8's who-may-do-what table names every gate a route uses, and no route is open by accident."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.routing import APIRoute

from app.core.lifespan import AGENT_ACCESS
from app.main import create_app

DOC = Path(__file__).resolve().parents[2] / "docs" / "ARCHITECTURE.md"
GATES = {
    "get_current_user", "require_user", "require_principal", "require_staff", "require_scout",
    "chat_access", "ask_access", "proposal_chat_access",
}
# Routes with no gate at all, on purpose: they answer anonymous callers with public rows only.
OPEN = {"/health", "/me", "/orgs/{slug}/news", "/funders/{slug}/news"}


def _table() -> str:
    text = DOC.read_text()
    return text[text.index("### Who may do what"):text.index("## 9.")]


def _routes(node, prefix=""):
    for route in getattr(node, "routes", []):
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        else:
            inner = getattr(route, "router", None) or getattr(route, "original_router", None)
            yield from _routes(inner if inner is not None else route, prefix + (getattr(route, "prefix", "") or ""))


def _gates(dependant) -> set[str]:
    found = set()
    for sub in dependant.dependencies:
        name = getattr(sub.call, "__name__", "")
        if name in GATES:
            found.add(name)
        found |= _gates(sub)
    return found


def _route_gates() -> dict[str, set[str]]:
    return {path: _gates(route.dependant) for path, route in _routes(create_app())}


def test_every_gate_a_route_uses_is_in_the_table():
    used = set().union(*_route_gates().values())
    used |= {check.__name__ for checks in AGENT_ACCESS.values() for check in checks}
    named = set(re.findall(r"`(\w+)`", _table()))
    assert used - named == set()


def test_no_route_is_open_unless_listed():
    open_routes = {path for path, gates in _route_gates().items() if not gates}
    assert open_routes == OPEN, "a route with no gate: add one, or add it to OPEN and the table"


def test_the_table_has_a_column_per_role():
    header = next(line for line in _table().splitlines() if line.startswith("| action"))
    assert [c.strip() for c in header.strip("|").split("|")] == [
        "action", "anon", "member", "admin", "steward", "staff", "gate",
    ]
