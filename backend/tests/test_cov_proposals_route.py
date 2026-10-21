"""/api/proposals: each route against a faked repository holding one proposal row in memory."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.api.routes import proposals as route
from app.proposals import fill, form, grade, polish
from app.repositories import documents as documents_repo
from app.repositories import funder_matches
from app.repositories import proposals as repo
from app.repositories import threads as threads_repo
from app.schemas.threads import ThreadMessagesOut

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
RAVI = {"id": "u-ravi", "name": "Ravi"}
ORG = {"id": 7, "slug": "jan-sahas", "name": "Jan Sahas"}
FUNDER = {"id": 3, "slug": "tata-trusts", "name": "Tata Trusts"}


def _work(**extra):
    return {
        "stage": 1,
        "requirements": [{"key": "12a", "label": "12A registration", "hard": False}],
        "gates": {},
        "earlier_phase": False,
        "sections": {},
        "facts": {},
        "log": [],
        "versions": [],
        **extra,
    }


def _row(work=None, can_edit=True):
    return {"id": 11, "title": "Water for Dewas", "created_at": NOW, "updated_at": NOW, "summary": {},
            "thread_id": None, "fit_score": 62, "org": ORG, "funder": FUNDER, "can_edit": can_edit,
            "work": work or _work()}


@pytest.fixture
def held(monkeypatch):
    """One proposal row; repo.save applies the route's change to it, as the real one does under the lock."""
    state = {"row": _row(), "saved": None}

    async def get(pool, pid):
        return copy.deepcopy(state["row"]) if pid == 11 and state["row"] else None

    async def me(pool):
        return RAVI

    async def save(pool, pid, change):
        if state["saved"] == "gone":
            return None
        applied = change(copy.deepcopy(state["row"]["work"]), state["row"]["title"])
        state["row"]["work"] = applied.work
        return applied

    async def districts(pool):
        return set()

    monkeypatch.setattr(repo, "get", get)
    monkeypatch.setattr(repo, "me", me)
    monkeypatch.setattr(repo, "save", save)
    monkeypatch.setattr(route.records, "districts", districts)
    return state


@pytest.fixture
def api(client_for):
    return client_for(route.router)


def test_new_work_carries_the_match_and_the_funders_form():
    match = {"id": 5, "score": 62, "run_at": NOW, "funder_type": "corporate_csr", "section_135_bound": False,
             "detail": {"criteria": [], "not_judged": []}}
    form = {"id": 40, "source_url": "https://tata.example/form.pdf", "fetched_at": NOW}
    work = route.new_work(match, form, "Jan Sahas")
    assert work["match"] == {"id": 5, "score": 62, "run_at": NOW.isoformat()}
    assert work["template"]["document_id"] == 40 and work["template"]["read_at"] == NOW.isoformat()
    assert [r["key"] for r in work["requirements"]] == ["12a", "80g", "csr1", "audits"]
    assert "Jan Sahas" in work["style"]
    unread = route.new_work(match, {**form, "fetched_at": None}, "Jan Sahas")
    assert unread["template"]["read_at"] is None
    assert route.new_work(match, None, "Jan Sahas")["template"] is None


async def test_list_filters_by_org_and_refuses_one_the_caller_cannot_read(api, monkeypatch):
    seen = {}

    async def find_org(pool, slug):
        return {"id": 7, "may_read": slug == "jan-sahas", "may_run": True, "name": "Jan Sahas"}

    async def list_proposals(pool, *, org_id, funder_id):
        seen.update(org=org_id, funder=funder_id)
        return [{k: v for k, v in _row().items() if k != "work"}]

    monkeypatch.setattr(funder_matches, "find_org", find_org)
    monkeypatch.setattr(repo, "list_proposals", list_proposals)
    async with api as c:
        ok = await c.get("/api/proposals", params={"org": "jan-sahas", "funder": 3})
        hidden = await c.get("/api/proposals", params={"org": "other"})
        everyone = await c.get("/api/proposals")
    assert ok.status_code == 200 and ok.json()[0]["title"] == "Water for Dewas"
    assert seen == {"org": None, "funder": None}  # the last call, with no filter
    assert hidden.status_code == 404
    assert everyone.status_code == 200


@pytest.mark.parametrize("found, match, status", [
    (None, None, 404),
    ({"id": 7, "name": "Jan Sahas", "may_read": False, "may_run": False}, None, 404),
    ({"id": 7, "name": "Jan Sahas", "may_read": True, "may_run": False}, None, 403),
    ({"id": 7, "name": "Jan Sahas", "may_read": True, "may_run": True}, None, 409),
])
async def test_create_is_refused_without_access_or_a_saved_match(api, monkeypatch, found, match, status):
    async def find_org(pool, slug):
        return found

    async def match_for(pool, org_id, funder_id):
        return match

    monkeypatch.setattr(funder_matches, "find_org", find_org)
    monkeypatch.setattr(repo, "match_for", match_for)
    async with api as c:
        r = await c.post("/api/proposals", json={"org": "jan-sahas", "funder_id": 3, "title": "x"})
    assert r.status_code == status


async def test_create_starts_step_one_from_the_saved_match(api, monkeypatch):
    created = {}

    async def find_org(pool, slug):
        return {"id": 7, "name": "Jan Sahas", "may_read": True, "may_run": True}

    async def match_for(pool, org_id, funder_id):
        return {"id": 5, "score": 62, "run_at": NOW, "funder_type": "trust", "section_135_bound": None,
                "detail": {"criteria": [], "not_judged": []}}

    async def funder_form(pool, funder_id):
        return None

    async def create(pool, **kwargs):
        created.update(kwargs)
        return 99

    monkeypatch.setattr(funder_matches, "find_org", find_org)
    monkeypatch.setattr(repo, "match_for", match_for)
    monkeypatch.setattr(repo, "funder_form", funder_form)
    monkeypatch.setattr(repo, "create", create)
    async with api as c:
        r = await c.post("/api/proposals", json={"org": "jan-sahas", "funder_id": 3, "title": "  Water  "})
    assert r.status_code == 201 and r.json() == {"id": 99}
    assert created["title"] == "Water" and created["org_id"] == 7
    assert created["summary"]["gates_total"] == 3  # no CSR-1 for a trust


async def test_get_returns_the_work_sections_tabs_and_the_callers_own_thread(api, held):
    async with api as c:
        r = await c.get("/api/proposals/11")
        missing = await c.get("/api/proposals/12")
    body = r.json()
    assert r.status_code == 200
    assert body["thread_id"].startswith("proposal-11-")
    assert [t["key"] for t in body["tabs"]] == ["case", "plan", "people", "money", "funder"]
    assert [t["step"] for t in body["tabs"]] == [3, 4, 4, 4, 4]
    assert {s["code"] for s in body["sections"]} >= {"A1", "F1"}
    assert body["summary"]["gates_total"] == 1
    assert missing.status_code == 404


async def test_rename_and_patch_save_through_work_apply(api, held):
    async with api as c:
        renamed = await c.patch("/api/proposals/11", json={"title": "Water, phase two"})
        answered = await c.patch("/api/proposals/11/work", json={"set": {"gates.12a": "yes"}})
    assert renamed.status_code == 200
    assert answered.status_code == 200 and answered.json()["work"]["gates"] == {"12a": "yes"}
    assert held["row"]["work"]["log"][-1]["by"] == RAVI


async def test_a_reader_is_refused_every_write(api, held):
    held["row"]["can_edit"] = False
    async with api as c:
        r = await c.patch("/api/proposals/11/work", json={"set": {"gates.12a": "yes"}})
    assert r.status_code == 403 and r.json()["detail"] == route.READ_ONLY


async def test_a_row_rls_hides_from_the_update_is_a_403(api, held):
    held["saved"] = "gone"
    async with api as c:
        r = await c.patch("/api/proposals/11/work", json={"set": {"gates.12a": "yes"}})
    assert r.status_code == 403


async def test_a_bad_path_is_400(api, held):
    async with api as c:
        r = await c.patch("/api/proposals/11/work", json={"set": {"summary": {}}})
    assert r.status_code == 400


async def test_a_stale_section_is_409_with_what_is_there(api, held):
    held["row"]["work"]["sections"] = {"A3": {"text": "Asha's", "rev": 2}}
    async with api as c:
        r = await c.patch("/api/proposals/11/work", json={"set": {"sections.A3.text": "mine"}, "rev": {"A3": 1}})
    assert r.status_code == 409
    assert r.json()["detail"]["section"] == "A3" and r.json()["detail"]["current"]["text"] == "Asha's"


async def test_ticking_another_orgs_file_is_422(api, held, monkeypatch):
    async def org_document_ids(pool, org_id, ids):
        return {41}

    monkeypatch.setattr(documents_repo, "org_document_ids", org_document_ids)
    async with api as c:
        refused = await c.patch("/api/proposals/11/work", json={"set": {"sources": [41, 42]}})
        kept = await c.patch("/api/proposals/11/work", json={"set": {"sources": [41]}})
    assert refused.status_code == 422
    assert kept.status_code == 200 and kept.json()["work"]["sources"] == [41]


async def test_advance_says_what_is_missing_then_moves_on(api, held):
    async with api as c:
        early = await c.post("/api/proposals/11/advance")
        await c.patch("/api/proposals/11/work", json={"set": {"gates.12a": "yes"}})
        moved = await c.post("/api/proposals/11/advance")
    assert early.status_code == 409
    assert early.json()["detail"]["missing"] == ["answer 12A registration"]
    assert moved.status_code == 200 and moved.json()["work"]["stage"] == 2



async def test_advance_jumps_ahead_only_when_every_step_on_the_way_is_done(api, held):
    async with api as c:
        back = await c.post("/api/proposals/11/advance?to=1")
        await c.patch("/api/proposals/11/work", json={"set": {"gates.12a": "yes"}})
        jump = await c.post("/api/proposals/11/advance?to=3")
        summary = (await c.get("/api/proposals/11")).json()["summary"]
    assert back.status_code == 400
    assert jump.status_code == 409 and "set the writing style" in jump.json()["detail"]["missing"]
    assert summary["furthest"] == 2

@pytest.fixture
def grader(monkeypatch):
    calls = []

    async def fake_grade(section, text, model):
        calls.append((section.code, text))
        return grade.Graded(covered=[], missing=["Current figures with source and year"])

    monkeypatch.setattr(grade, "grade", fake_grade)
    monkeypatch.setattr("app.agent.models.resolve_model", lambda spec: object())
    return calls


async def test_marking_a_part_done_grades_its_text(api, held, grader):
    held["row"]["work"]["sections"] = {"A3": {"text": "Wells in Dewas run dry.", "rev": 1}}
    async with api as c:
        r = await c.patch("/api/proposals/11/work", json={"set": {"sections.A3.done": True}, "rev": {"A3": 1}})
    part = r.json()["work"]["sections"]["A3"]
    assert r.status_code == 200 and grader == [("A3", "Wells in Dewas run dry.")]
    assert part["score"] == 1 and part["missing"] == ["Current figures with source and year"]


@pytest.mark.parametrize("part, change, rev", [
    ({"text": "", "rev": 1}, {"sections.A3.done": True}, {"A3": 1}),  # nothing written
    ({"text": "x", "rev": 1, "missing": []}, {"sections.A3.done": True}, {"A3": 1}),  # graded on this text
    ({"text": "x", "rev": 1}, {"sections.A3.done": False}, {"A3": 1}),  # not marked done
])
async def test_grading_is_skipped_when_there_is_nothing_new_to_grade(api, held, grader, part, change, rev):
    held["row"]["work"]["sections"] = {"A3": part}
    async with api as c:
        r = await c.patch("/api/proposals/11/work", json={"set": change, "rev": rev})
    assert r.status_code == 200 and grader == []


async def test_a_stale_done_is_not_graded_and_is_refused(api, held, grader):
    held["row"]["work"]["sections"] = {"A3": {"text": "x", "rev": 2}}
    async with api as c:
        r = await c.patch("/api/proposals/11/work", json={"set": {"sections.A3.done": True}, "rev": {"A3": 1}})
    assert grader == [] and r.status_code == 409


def test_names_are_the_org_the_funder_and_live_name_facts():
    row = _row(_work(facts={"k1": {"kind": "name", "value": "Gram Vikas", "status": "confirmed"},
                            "k2": {"kind": "name", "value": "Old Partner", "status": "rejected"},
                            "k3": {"kind": "number", "value": "120", "status": "confirmed"}}))
    names = route._names(row)
    assert {"jan sahas", "tata trusts", "gram vikas"} <= names
    assert "old partner" not in names


def _written(**extra):
    return _work(stage=3, sections={"A3": {"text": "Wells in Dewas run dry for 120 days.", "rev": 2}}, **extra)


@pytest.fixture
def smoother(monkeypatch):
    monkeypatch.setattr("app.agent.models.resolve_model", lambda spec: object())

    def use(result):
        async def smooth(written, style, model):
            return result

        monkeypatch.setattr(polish, "smooth", smooth)

    return use


async def test_polish_keeps_wording_that_changes_no_claim(api, held, smoother):
    held["row"]["work"] = _written()
    smoother({"A3": "For 120 days, wells in Dewas run dry."})
    async with api as c:
        r = await c.post("/api/proposals/11/polish")
    assert r.status_code == 200
    polished = r.json()["work"]["polished"]
    assert polished["parts"] == {"A3": "For 120 days, wells in Dewas run dry."}
    assert polished["revs"] == {"A3": 2} and polished["by"] == RAVI


async def test_polish_refuses_wording_that_changed_a_figure(api, held, smoother):
    held["row"]["work"] = _written()
    smoother({"A3": "Wells in Dewas run dry for 150 days."})
    async with api as c:
        r = await c.post("/api/proposals/11/polish")
    assert r.status_code == 409
    assert r.json()["detail"]["differences"] == ["Problem and baseline: 120 became 150"]


async def test_polish_is_502_when_the_model_fails_and_409_with_nothing_written(api, held, smoother):
    smoother(None)
    async with api as c:
        empty = await c.post("/api/proposals/11/polish")
        held["row"]["work"] = _written()
        failed = await c.post("/api/proposals/11/polish")
    assert empty.status_code == 409 and empty.json()["detail"]["message"] == "Nothing is written yet."
    assert failed.status_code == 502


@pytest.fixture
def vault(monkeypatch):
    saved = {}
    monkeypatch.setattr(route, "get_settings", lambda: SimpleNamespace(storage_enabled=True))

    async def upload(bucket, key, data, content_type):
        saved.update(bucket=bucket, key=key, data=data, type=content_type)
        return key if saved.get("reachable", True) else None

    async def insert_draft(pool, **kwargs):
        saved["draft"] = kwargs
        return 501

    monkeypatch.setattr(route.storage, "upload", upload)
    monkeypatch.setattr(repo, "insert_draft", insert_draft)
    return saved


async def test_a_version_is_a_word_file_in_the_vault_and_logged(api, held, vault):
    held["row"]["work"] = _written()
    async with api as c:
        r = await c.post("/api/proposals/11/versions")
    assert r.status_code == 201
    entry = r.json()["work"]["versions"][-1]
    assert entry["n"] == 1 and entry["document_id"] == 501 and entry["by"] == RAVI
    assert vault["key"] == "7/proposals/11/v1.docx" and vault["data"][:2] == b"PK"
    assert vault["draft"]["title"] == "Water for Dewas, version 1"
    assert vault["draft"]["content_md"].startswith("## Problem and baseline")


async def test_a_version_needs_storage_text_and_a_reachable_bucket(api, held, vault, monkeypatch):
    async with api as c:
        empty = await c.post("/api/proposals/11/versions")
        held["row"]["work"] = _written()
        vault["reachable"] = False
        unreachable = await c.post("/api/proposals/11/versions")
        monkeypatch.setattr(route, "get_settings", lambda: SimpleNamespace(storage_enabled=False))
        off = await c.post("/api/proposals/11/versions")
    assert empty.status_code == 409
    assert unreachable.status_code == 502
    assert off.status_code == 503


TEMPLATE = {"document_id": 40, "read_at": NOW.isoformat()}
HEADINGS = [
    {"code": "T1", "number": "4", "label": "Problem Statement", "ask": "The problem", "kind": "prose",
     "limit": {"n": 3000, "unit": "chars"}, "uses": ["A3"], "only_if": None},
    {"code": "T2", "number": None, "label": "PAN Card Number", "ask": "", "kind": "field", "limit": None,
     "uses": [], "only_if": None},
]


@pytest.fixture
def former(monkeypatch, vault):
    """The form reader and filler faked: counts reads, answers as told."""
    seen = {"reads": 0, "answers": {}, "fail": None}
    monkeypatch.setattr(route, "get_settings", lambda: SimpleNamespace(
        storage_enabled=True, model="m", research_model="r"))
    monkeypatch.setattr("app.agent.models.resolve_model", lambda spec: spec)

    async def read(pool, template, org_id, sections, model):
        seen["reads"] += 1
        seen["read_model"] = model
        if seen["fail"]:
            raise seen["fail"]
        return {"document_id": template["document_id"], "title": "RF template", "headings": HEADINGS,
                "pages_cut": False, "read_at": NOW.isoformat()}

    async def fill_in(headings, written, style, model):
        seen["fill_model"] = model
        return seen["answers"]

    monkeypatch.setattr(form, "read", read)
    monkeypatch.setattr(fill, "fill", fill_in)
    return seen


async def test_a_version_in_the_funders_form_carries_its_headings_and_a_report(api, held, vault, former):
    held["row"]["work"] = _written(template=TEMPLATE)
    former["answers"] = {"T1": "Wells in Dewas run dry for 120 days."}
    async with api as c:
        r = await c.post("/api/proposals/11/versions", json={"shape": "form"})
    assert r.status_code == 201
    work = r.json()["work"]
    entry = work["versions"][-1]
    assert entry["title"] == "Version 1, in the Tata Trusts form" and entry["shape"] == "form"
    assert entry["report"] == {"answered": ["4. Problem Statement"], "cut": {}, "as_written": [], "add": [],
                               "you_fill": ["PAN Card Number"]}
    assert vault["draft"]["title"] == "Water for Dewas, version 1, in the Tata Trusts form"
    assert vault["draft"]["content_md"] == ("## 4. Problem Statement\n\nWells in Dewas run dry for 120 days.\n\n"
                                            "## PAN Card Number\n\n[You fill: PAN Card Number]")
    assert work["template"]["outline"]["headings"] == HEADINGS
    assert former["read_model"] == "r" and former["fill_model"] == "m"


async def test_the_form_is_read_once_and_read_again_when_another_is_chosen(api, held, vault, former):
    held["row"]["work"] = _written(template=TEMPLATE)
    async with api as c:
        await c.post("/api/proposals/11/versions", json={"shape": "form"})
        second = await c.post("/api/proposals/11/versions", json={"shape": "form"})
        held["row"]["work"]["template"]["document_id"] = 41
        third = await c.post("/api/proposals/11/versions", json={"shape": "form"})
    assert second.status_code == 201 and third.status_code == 201
    assert former["reads"] == 2
    assert third.json()["work"]["template"]["outline"]["document_id"] == 41


async def test_a_failed_fill_still_saves_the_parts_as_written(api, held, vault, former):
    held["row"]["work"] = _written(template=TEMPLATE)
    async with api as c:
        r = await c.post("/api/proposals/11/versions", json={"shape": "form"})
    assert r.status_code == 201
    assert r.json()["work"]["versions"][-1]["report"]["as_written"] == ["4. Problem Statement"]


@pytest.mark.parametrize("work, fail, status", [
    ({}, None, 409),
    ({"template": TEMPLATE, "skipped_template": True}, None, 409),
    ({"template": TEMPLATE}, form.Unreadable("The funder's form must be a PDF or Word file."), 422),
    ({"template": TEMPLATE}, RuntimeError("overloaded"), 502),
])
async def test_a_version_in_the_form_needs_a_form_sangam_can_read(api, held, vault, former, work, fail, status):
    held["row"]["work"] = _written(**work)
    former["fail"] = fail
    async with api as c:
        r = await c.post("/api/proposals/11/versions", json={"shape": "form"})
    assert r.status_code == status
    assert held["row"]["work"]["versions"] == [] and "data" not in vault
    if status == 422:
        assert r.json()["detail"] == "The funder's form must be a PDF or Word file."


async def test_a_reader_cannot_save_a_version_in_the_form(api, held, vault, former):
    held["row"]["work"] = _written(template=TEMPLATE)
    held["row"]["can_edit"] = False
    async with api as c:
        r = await c.post("/api/proposals/11/versions", json={"shape": "form"})
    assert r.status_code == 403 and former["reads"] == 0


async def test_messages_are_empty_before_the_first_question(api, held, monkeypatch):
    async def can_open(pool, *, thread_id, user_id):
        return False

    monkeypatch.setattr(threads_repo, "can_open", can_open)
    async with api as c:
        r = await c.get("/api/proposals/11/messages")
    assert r.status_code == 200 and r.json()["messages"] == []
    assert r.json()["thread_id"].startswith("proposal-11-")


async def test_messages_are_read_from_the_proposal_graph(api, held, monkeypatch):
    seen = {}

    async def can_open(pool, *, thread_id, user_id):
        return True

    async def saved_messages(request, owner_pool, user_id, thread_id, *, graph_name):
        seen["graph"] = graph_name
        return ThreadMessagesOut(thread_id=thread_id, messages=[])

    monkeypatch.setattr(threads_repo, "can_open", can_open)
    monkeypatch.setattr(route, "saved_messages", saved_messages)
    async with api as c:
        r = await c.get("/api/proposals/11/messages")
    assert r.status_code == 200 and seen == {"graph": "proposal_graph"}


@pytest.fixture
def angler(monkeypatch):
    monkeypatch.setattr("app.agent.models.resolve_model", lambda spec: object())

    def use(result):
        async def angles(work, model, avoid):
            if isinstance(result, Exception):
                raise result
            use.avoid = avoid
            return result

        monkeypatch.setattr(route.research, "angles", angles)

    return use


async def test_research_angles_wait_for_the_case_then_come_back_to_edit(api, held, angler):
    angler((["MGNREGA days worked, Dewas"], ["Jan Sahas wells"]))
    async with api as c:
        early = await c.get("/api/proposals/11/research/angles")
        held["row"]["work"]["sections"] = {"A2": {"text": "Dewas", "done": True}, "A3": {"text": "Dry", "done": True}}
        ready = await c.get("/api/proposals/11/research/angles")
    assert early.status_code == 409
    assert early.json()["detail"]["missing"] == ["mark Context and target area done", "mark Problem and baseline done"]
    assert ready.json() == {"angles": ["MGNREGA days worked, Dewas"], "dropped": ["Jan Sahas wells"]}
    assert {"jan sahas", "tata trusts"} <= angler.avoid


async def test_research_angles_502_when_the_model_fails_and_403_for_a_reader(api, held, angler):
    angler(RuntimeError("down"))
    held["row"]["work"]["sections"] = {"A2": {"done": True}, "A3": {"done": True}}
    async with api as c:
        failed = await c.get("/api/proposals/11/research/angles")
        held["row"]["can_edit"] = False
        refused = await c.get("/api/proposals/11/research/angles")
    assert failed.status_code == 502 and refused.status_code == 403
