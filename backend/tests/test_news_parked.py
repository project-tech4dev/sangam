"""GDELT and India CSR are parked: their code stays, nothing calls them (D16)."""

from app.ingest import runner
from app.ingest.adapters import gdelt, india_csr  # noqa: F401 - the code stays importable


def test_nothing_runs_a_parked_adapter():
    assert set(runner.ADAPTERS).isdisjoint(runner.PARKED)
    assert set(runner.PARKED) == {"gdelt", "india_csr"}


async def test_asking_for_a_parked_source_says_so_rather_than_going_silent(monkeypatch):
    calls = []

    async def fake_item(conn, run_id, source, kind, status, **kw):
        calls.append((source, status, kw.get("reason", "")))
    monkeypatch.setattr(runner, "_item", fake_item)
    for key in runner.PARKED:
        await runner._refuse_parked(None, 1, key)
    assert [c[:2] for c in calls] == [("gdelt", "refused"), ("india_csr", "refused")]
    assert "parked" in calls[0][2]
