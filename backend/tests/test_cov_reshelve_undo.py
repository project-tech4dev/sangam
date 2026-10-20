"""reshelve's CLI over the test transaction, and undo's refusals."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.ingest import reshelve, undo
from app.integrations import storage
from tests.test_cov_promote import funder, one, tag

pytestmark = pytest.mark.integration


class _Held:
    """The test's connection, minus commit and close: reshelve --yes commits, and the fixture must roll back."""

    def __init__(self, conn) -> None:
        self.conn = conn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def execute(self, *args, **kwargs):
        return await self.conn.execute(*args, **kwargs)

    async def commit(self) -> None:
        return None


@pytest.fixture
def cli(db, monkeypatch):
    def run(*argv: str, enabled: bool = True, url: str = "postgresql://test") -> None:
        monkeypatch.setattr(sys, "argv", ["reshelve", *argv])
        monkeypatch.setattr(reshelve.storage, "get_settings", lambda: SimpleNamespace(storage_enabled=enabled))
        monkeypatch.setenv("DATABASE_URL", url)

        async def connect(*a, **k):
            return _Held(db)
        monkeypatch.setattr(reshelve.psycopg.AsyncConnection, "connect", connect)
    return run


async def _documents(db) -> tuple[int, int, int]:
    fid = await funder(db, f"Zz Reshelve Ltd {tag()}")
    slug = (await one(db, "SELECT slug FROM funders WHERE id = %s", fid))["slug"]
    ids = []
    for key in (f"abcd1234/{'b' * 64}-report.pdf", f"funders/{slug}/2023-24-report.pdf", f"ffff0000/{'c' * 64}-x.pdf"):
        row = await one(db, "INSERT INTO documents (funder_id, doc_type, source_url, storage_path, as_of) "
                            "VALUES (%s, 'annual_report', %s, %s, 'FY2023-24') RETURNING id",
                        fid, f"https://zz-{tag()}.example.org/r.pdf", storage.qualify(storage.SOURCE_ARCHIVE, key))
        ids.append(row["id"])
    return fid, ids[0], ids[2]


async def test_a_dry_run_names_each_move_and_changes_nothing(db, cli, capsys):
    _, first, _ = await _documents(db)
    cli()
    assert await reshelve.main() == 0
    out = capsys.readouterr().out
    assert "would move" in out and "dry run" in out
    assert "abcd1234" in (await one(db, "SELECT storage_path FROM documents WHERE id = %s", first))["storage_path"]


async def test_yes_moves_what_it_can_and_reports_what_it_could_not(db, cli, monkeypatch, capsys):
    _, first, stuck = await _documents(db)

    async def shelve(key, slug, as_of, digest):
        return key if key.startswith("ffff0000/") else f"funders/{slug}/moved-report.pdf"
    monkeypatch.setattr(reshelve, "_shelve", shelve)
    cli("--yes")
    assert await reshelve.main() == 1
    out = capsys.readouterr().out
    assert "could not move" in out and "already shelved" in out
    moved = (await one(db, "SELECT storage_path FROM documents WHERE id = %s", first))["storage_path"]
    assert moved.endswith("/moved-report.pdf")
    assert "ffff0000" in (await one(db, "SELECT storage_path FROM documents WHERE id = %s", stuck))["storage_path"]


async def test_without_storage_or_a_database_it_stops(cli, capsys):
    cli(enabled=False)
    assert await reshelve.main() == 1
    cli(url="")
    assert await reshelve.main() == 1
    err = capsys.readouterr().err
    assert "not configured" in err and "DATABASE_URL" in err


async def _staff(db):
    from app.core.security import CallerScope

    row = await one(db, "SELECT id FROM users WHERE is_staff LIMIT 1")
    if row is None:
        pytest.skip("no staff user seeded")
    return CallerScope(row["id"], True)


async def test_undo_of_an_unknown_save_is_a_lookup_error(db):
    with pytest.raises(LookupError):
        await undo.undo(db, -1, None)


async def test_a_row_used_elsewhere_refuses_the_undo_until_it_is_gone(db):
    staff = await _staff(db)
    before = await funder(db, f"Zz Before Ltd {tag()}", website="https://before.example.org")
    promotion = await undo.start(db, None, f"zz-elsewhere-{tag()}", staff.user_id)
    fid = await funder(db, f"Zz Elsewhere Ltd {tag()}")
    await db.execute("UPDATE funders SET website = 'https://during.example.org' WHERE id = %s", (before,))
    assert await undo.finish(db, promotion)
    # Written outside the save, and rfps does not cascade: undoing the funder would orphan it.
    rfp = await one(db, "INSERT INTO rfps (funder_id, title) VALUES (%s, 'Zz call') RETURNING id", fid)
    with pytest.raises(undo.UndoRefused, match="used elsewhere"):
        await undo.undo(db, promotion, staff.user_id)
    assert await one(db, "SELECT 1 FROM funders WHERE id = %s", fid)

    await db.execute("DELETE FROM rfps WHERE id = %s", (rfp["id"],))
    done = await undo.undo(db, promotion, staff.user_id)
    assert (done["removed"], done["restored"]) == (1, 1)
    assert not await one(db, "SELECT 1 FROM funders WHERE id = %s", fid)
    assert (await one(db, "SELECT website FROM funders WHERE id = %s", before))["website"] == "https://before.example.org"
    with pytest.raises(undo.UndoRefused, match="already undone"):
        await undo.undo(db, promotion, staff.user_id)


async def test_delete_research_removes_every_row_of_a_slug_with_no_save(db):
    slug = f"zz-delete-{tag()}"
    for day in (0, 1):
        await db.execute("INSERT INTO entity_research (entity_name, slug, status, summary, researched_on) "
                         "VALUES ('Zz', %s, 'complete', 's', current_date - %s)", (slug, day))
    assert await undo.delete_research(db, slug) == 2
