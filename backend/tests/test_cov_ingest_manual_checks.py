"""A staff member's own registry check: who may record one, and what it does to the row on file."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from app.ingest import manual_checks
from app.ingest.writer import Conflict
from tests.cov_ingest_fakes import ScriptConn, ScriptPool

STAFF = UUID(int=1)
URL = "https://www.incometax.gov.in/verify"
ARPAN = {"id": 7, "name": "Arpan", "slug": "arpan"}
NOW = datetime(2026, 10, 21, 6, 0, tzinfo=UTC)


def ident(**over) -> dict:
    return {"id": 50, "org_id": 7, "id_value": "AAATA1234C", "status": "registered", "source_type": "registry",
            "evidence": "evidenced", "checked_at": datetime(2026, 1, 1, tzinfo=UTC), "valid_from": None,
            "valid_until": None, "application_ref": None, "source_url": "https://registry.example/a",
            "evidence_document_id": None, **over}


def conn(*, staff=True, orgs=(ARPAN,), doc=None, current=(), by_number=None, open_row=None, one_current=(),
         final=None) -> ScriptConn:
    return ScriptConn([
        ("FROM users", {"is_staff": staff}),
        ("FROM orgs", list(orgs)),
        ("FROM documents", doc),
        ("is_current ORDER BY id LIMIT 3", list(current)),
        ("lower(id_value) = lower(%s)", by_number),
        ("id_value IS NULL", open_row),
        ("is_current ORDER BY id LIMIT 2", list(one_current)),
        ("FROM org_identifiers WHERE id = %s", final),
    ])


async def record(c: ScriptConn, **over) -> str:
    args = {"org": "arpan", "id_type": "pan", "status": "registered", "source_url": URL, "id_value": "AAATA1234C",
                "user_id": STAFF}
    return await manual_checks.record(ScriptPool(c), **{**args, **over})


class TestRefusal:
    @pytest.mark.parametrize(("over", "phrase"), [
        ({"user_id": None}, "no signed-in staff member"),
        ({"id_type": "gst"}, "id_type must be one of"),
        ({"status": "valid"}, "status must be one of"),
        ({"source_url": "registry.gov.in"}, "source_url must be the http(s)"),
        ({"note": "x" * 501}, "under 500 characters"),
    ])
    def test_each_bad_argument(self, over, phrase):
        args = {"id_type": "pan", "status": "registered", "source_url": URL, "note": "", "user_id": STAFF}
        assert phrase in manual_checks.refusal(**{**args, **over})

    def test_a_good_check_passes(self):
        assert manual_checks.refusal(id_type="pan", status="registered", source_url=URL, note="",
                                     user_id=STAFF) is None


class TestCheckInstant:
    def test_blank_is_now(self):
        assert manual_checks.check_instant("", NOW) == NOW

    def test_today_in_ist_is_now(self):
        assert manual_checks.check_instant("2026-10-21", NOW) == NOW

    def test_an_earlier_day_is_its_ist_noon(self):
        when = manual_checks.check_instant("2026-10-01", NOW)
        assert when.date() == date(2026, 10, 1) and when.hour == 12 and when.tzinfo == manual_checks.IST

    def test_the_future_and_nonsense_are_refused(self):
        assert "future" in manual_checks.check_instant("2026-12-01", NOW)
        assert "date like" in manual_checks.check_instant("yesterday", NOW)


class TestReplacedLine:
    def test_names_everything_it_replaced(self):
        line = manual_checks._replaced(ident(valid_from=date(2020, 1, 1), valid_until=date(2025, 3, 31),
                                             evidence_document_id=9))
        assert line == ("replaced registered, registry, evidenced, valid from 2020-01-01, valid to 2025-03-31, "
                        "source https://registry.example/a, document 9, checked 2026-01-01")

    def test_an_unranked_undated_row(self):
        line = manual_checks._replaced(ident(source_type=None, evidence=None, source_url=None, checked_at=None))
        assert line == "replaced registered, unranked, no tier, source none recorded, never dated"


class TestRecordRefuses:
    async def test_an_argument_refusal_reaches_no_database(self):
        out = await manual_checks.record(ScriptPool(), org="a", id_type="pan", status="registered",
                                         source_url=URL, user_id=None)
        assert out.startswith("REFUSED")

    async def test_a_future_date(self):
        assert "future" in await record(conn(), checked_on="2999-01-01")

    async def test_not_staff(self):
        assert "only a staff member's check" in await record(conn(staff=False))

    async def test_no_org(self):
        assert "no organisation in the catalog matches" in await record(conn(orgs=()))

    async def test_two_orgs(self):
        out = await record(conn(orgs=(ARPAN, {"id": 8, "name": "Arpan", "slug": "arpan-2"})), org="Arpan")
        assert "names more than one organisation" in out and "[org:8]" in out

    async def test_an_org_marker_is_looked_up_by_id(self):
        c = conn(orgs=())
        await record(c, org="[org:7]")
        assert c.sql("FROM orgs")[0][1] == (7,)

    @pytest.mark.parametrize(("doc", "phrase"), [
        (None, "does not exist"),
        ({"id": 3, "org_id": None, "title": "x"}, "belongs to no organisation"),
        ({"id": 3, "org_id": 9, "title": "x"}, "belongs to [org:9]"),
    ])
    async def test_a_document_from_elsewhere(self, doc, phrase):
        assert phrase in await record(conn(doc=doc), document_id=3)

    async def test_two_current_rows_without_a_number(self):
        out = await record(conn(current=(ident(), ident(id=51, id_value=None))), id_value="")
        assert "holds 2 current pan identifiers" in out and "row 51 (no number" in out

    async def test_an_application_with_nothing_to_show(self):
        assert "Nothing was written" in await record(conn(), status="applied", id_value="")


class TestRecordOnAnEqualRow:
    async def test_an_agreeing_newer_check_confirms(self):
        c = conn(by_number=ident(), final=ident())
        out = await record(c, note="  saw it   on the portal ")
        assert out.startswith("Confirmed Arpan [org:7]: pan (AAATA1234C) is still registered (registry, evidenced)")
        [(_sql, params)] = c.sql("UPDATE org_identifiers SET checked_at")
        assert "manual_check: registered — saw it on the portal" in params[2]

    async def test_a_numberless_check_borrows_the_number_on_file(self):
        c = conn(current=(ident(),), by_number=ident(), final=ident())
        out = await record(c, id_value="")
        assert "pan (AAATA1234C)" in out

    async def test_a_confirmation_reports_a_different_application_ref(self):
        c = conn(by_number=ident(application_ref="ACK-1"), final=ident())
        out = await record(c, application_ref="ACK-2")
        assert "Conflicts, kept for a person" in out and "'ACK-1'" in out

    async def test_a_document_replacing_an_earlier_one_is_noted(self):
        c = conn(doc={"id": 4, "org_id": 7, "title": "Certificate"}, by_number=ident(evidence_document_id=3),
                 final=ident())
        await record(c, document_id=4)
        [(_, params)] = c.sql("UPDATE org_identifiers SET checked_at")
        assert "(evidence document 4 replaces document 3)" in params[2]
        assert params[-2] == 4  # evidence_document_id set from the document

    async def test_a_newer_check_with_a_different_status_replaces(self):
        c = conn(by_number=ident(status="expired"), final=ident(source_type="manual_check", evidence="claimed"))
        out = await record(c)
        assert out.startswith("Recorded a manual check for Arpan [org:7]: pan (AAATA1234C) is registered, claimed")
        assert "A newer check of equal rank supersedes the earlier one: replaced expired" in out
        assert "status = %s" in c.sql("UPDATE org_identifiers SET checked_at")[0][0]

    async def test_an_older_check_with_a_different_status_is_only_noted(self):
        c = conn(by_number=ident(status="expired"), final=ident(status="expired"))
        out = await record(c, checked_on="2025-06-01")
        assert "did not change the stored pan (AAATA1234C): it stays expired from registry" in out
        assert "Conflicts, kept for a person" in out
        assert c.sql("SET notes = concat_ws")

    async def test_check_blocked_never_replaces_and_says_why(self):
        c = conn(by_number=ident(), final=ident())
        out = await record(c, status="check_blocked")
        assert "check_blocked means the registry could not be read" in out


class TestRecordThroughTheWriter:
    @pytest.fixture
    def writer(self, monkeypatch):
        calls = []

        def set_outcome(outcome, changes=None, conflicts=()):
            async def write(c, rec, org_id, document_id):
                calls.append((rec, org_id))
                return outcome, changes or {}, list(conflicts)
            monkeypatch.setattr(manual_checks, "write_org_identifier", write)
            return calls
        return set_outcome

    async def test_a_new_number_is_added_and_stamped(self, writer):
        calls = writer("added")
        c = conn(by_number=(None, ident(source_type="manual_check")), final=ident(source_type="manual_check"))
        out = await record(c)
        assert calls[0][1] == 7 and calls[0][0].source_type == "manual_check"
        assert out.startswith("Recorded a manual check for Arpan [org:7]") and "Identifier row 50" in out
        assert c.sql("evidence_document_id = NULL")

    async def test_a_number_held_by_another_org_is_not_recorded(self, writer):
        writer("held")
        c = conn(by_number=ident(org_id=99))
        assert (await record(c)).startswith("Not recorded for Arpan [org:7]: pan AAATA1234C is held by another")

    async def test_the_writer_taking_a_persons_row_says_what_it_replaced(self, writer):
        writer("updated", {"source_type": ("x", "manual_check"), "status": ("applied", "registered")})
        person = ident(source_type=None, status="applied", checked_at=None)
        c = conn(by_number=person, final=ident(source_type="manual_check"))
        out = await record(c)
        assert "It supersedes the stored value: replaced applied, unranked" in out

    async def test_a_matched_row_is_only_noted(self, writer):
        writer("matched", conflicts=[Conflict("org_identifiers", "[org:7] pan", "status", "registered", None,
                                              None, "expired", "manual_check", URL)])
        c = conn(by_number=ident(source_type=None, status="registered"), final=ident(source_type=None))
        out = await record(c, status="expired")
        assert "it stays registered from a person (unranked)" in out and "Conflicts" in out

    async def test_no_single_row_to_note_on(self, writer):
        writer("matched")
        out = await record(conn(), id_value="", status="not_found")
        assert "found no single pan row to note it on" in out
