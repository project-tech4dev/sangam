"""A scripted pool for Import tool tests: each query is answered by the first rule whose text it contains."""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from typing import Any

from app.core.security import CallerScope, chat_scope


@contextmanager
def running_as(scope: CallerScope | None):
    token = chat_scope.set(scope)
    try:
        yield
    finally:
        chat_scope.reset(token)


class ScriptConn:
    """Rules are (substring, answers); each match takes the next answer and the last one repeats."""

    def __init__(self, rules: list[tuple[str, Any]] | None = None):
        self.rules = [(needle, list(answers) if isinstance(answers, tuple) else [answers])
                      for needle, answers in (rules or [])]
        self.calls: list[tuple[str, Any]] = []

    def on(self, needle: str, *answers: Any) -> ScriptConn:
        self.rules.insert(0, (needle, list(answers)))
        return self

    def _answer(self, sql: str) -> Any:
        for needle, answers in self.rules:
            if needle in sql:
                if isinstance(answers[0], BaseException):
                    raise answers.pop(0) if len(answers) > 1 else answers[0]
                return answers.pop(0) if len(answers) > 1 else answers[0]
        return []

    async def execute(self, sql: str, params: Any = ()) -> SimpleNamespace:
        self.calls.append((sql, params))
        rows = self._answer(sql)
        if isinstance(rows, dict) or rows is None:
            rows = [] if rows is None else [rows]

        async def one():
            return rows[0] if rows else None

        async def all_():
            return list(rows)

        return SimpleNamespace(fetchone=one, fetchall=all_)

    @asynccontextmanager
    async def transaction(self):
        yield

    def sql(self, needle: str) -> list[tuple[str, Any]]:
        return [(s, p) for s, p in self.calls if needle in s]


class ScriptPool:
    def __init__(self, conn: ScriptConn | None = None):
        self.conn = conn or ScriptConn()

    @asynccontextmanager
    async def connection(self):
        yield self.conn


class BrokenPool:
    """A pool whose connection fails: the tool must return its failure, not raise."""

    @asynccontextmanager
    async def connection(self):
        raise RuntimeError("database down")
        yield  # pragma: no cover
