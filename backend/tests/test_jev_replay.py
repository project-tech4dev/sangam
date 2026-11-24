"""scripts/jev_replay.py: labels and questions from recorded traces, with a fake Langfuse and Jev."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import SimpleNamespace

from app.core.config import Settings
from app.integrations.typesafe import Decision

_PATH = pathlib.Path(__file__).parents[2] / "scripts" / "jev_replay.py"
_spec = importlib.util.spec_from_file_location("jev_replay", _PATH)
replay = importlib.util.module_from_spec(_spec)
sys.modules["jev_replay"] = replay
_spec.loader.exec_module(replay)


def obs(**kw):
    return SimpleNamespace(**{"traceId": None, "sessionId": None, "startTime": None, "input": None, "name": None} | kw)


class FakeObservations:
    def __init__(self, roots, tools):
        self.roots, self.tools = roots, tools

    def get_many(self, *, limit, cursor, **kw):
        rows = self.tools.get(kw["trace_id"], []) if "trace_id" in kw else self.roots
        # Two pages, so the cursor loop is exercised.
        half = len(rows) // 2
        if cursor is None and half:
            return SimpleNamespace(data=rows[:half], meta=SimpleNamespace(cursor="next"))
        return SimpleNamespace(data=rows[half:] if cursor else rows, meta=SimpleNamespace(cursor=None))


ROOTS = [
    obs(traceId="t2", sessionId="s1", startTime="2026-11-20T10:05", input="and Goonj?"),
    obs(traceId="t1", sessionId="s1", startTime="2026-11-20T10:00", input="How well does KABIL fit Axis?"),
    obs(traceId="t3", sessionId="s2", startTime="2026-11-20T11:00", input={"resume": "yes"}),
    obs(traceId="t4", sessionId="s3", startTime="2026-11-20T12:00", input="what is the weather today?"),
]
TOOLS = {
    "t1": [obs(name="compare_fit", startTime="2", input="{}"),
           obs(name="read_file", startTime="1", input='{"file_path": "/skills/funder-comparison/SKILL.md"}')],
    "t2": [obs(name="read_file", startTime="1", input={"file_path": "/large_tool_results/x"}),
           obs(name="db_query", startTime="2", input="not json")],
    "t4": [],
}
API = SimpleNamespace(observations=FakeObservations(ROOTS, TOOLS))


def test_turns_skip_resumes_and_carry_the_previous_question():
    turns = replay.turns(API, "production", None)
    assert [(t["trace"], t["previous"]) for t in turns] == [
        ("t1", None), ("t2", "How well does KABIL fit Axis?"), ("t4", None)]


def test_labels_come_from_the_tool_observations():
    assert replay.label(API, "t1", "production") == replay.Did(("funder-comparison",), True)
    assert replay.label(API, "t2", "production") == replay.Did((), True)
    assert replay.label(API, "t4", "production") == replay.Did((), False)


def _decision(route, skill, latency=100):
    return Decision({"route": {"type": "choice", "choice": route, "confidence": 0.95, "probabilities": {}},
                     "skill": {"type": "choice", "choice": skill, "confidence": 0.6, "probabilities": {}}},
                    "jev-latest", 50, False, latency, 0.000002)


def test_main_replays_and_reports(monkeypatch, tmp_path, capsys):
    picks = iter([_decision("catalog", "funder-comparison"), _decision("catalog", "none", 300), None])
    monkeypatch.setattr(replay, "get_settings", lambda: Settings(_env_file=None, typesafe_api_key="k"))
    monkeypatch.setattr(replay, "get_client", lambda: SimpleNamespace(api=API))
    monkeypatch.setattr(replay, "decide", lambda *a, **kw: next(picks))
    out = tmp_path / "jev.jsonl"
    assert replay.main(["--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "3 typed Ask questions" in printed
    assert "2 decided, 1 failed" in printed
    assert "route: agrees 2/2 (100%)" in printed
    assert "skill: agrees 2/2 (100%)" in printed
    assert "at p>=0.9: 0 decided" in printed  # skill confidence 0.6
    assert len(out.read_text().splitlines()) == 2


def test_main_without_a_key_stops(monkeypatch, capsys):
    monkeypatch.setattr(replay, "get_settings", lambda: Settings(_env_file=None))
    assert replay.main([]) == 1
    assert "TYPESAFE_API_KEY" in capsys.readouterr().out


def test_report_with_nothing_decided(capsys):
    replay.report([], 4)
    assert "No decisions (4 calls failed)" in capsys.readouterr().out
