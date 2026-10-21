"""readers.read end to end with fake reader graphs: the claim under the lock, each outcome, and the public task."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.core.security import CallerScope
from app.ingest import run_sources
from app.proposals import context, readers
from app.proposals.middleware import PUBLIC_RUN
from app.repositories import profile_facts
from app.repositories import proposals as repo

ADMIN = {"id": str(UUID(int=5)), "name": "Admin"}


class FakePool:
    def __init__(self, rows):
        self.rows = rows

    @asynccontextmanager
    async def connection(self):
        yield self

    async def execute(self, sql, params=()):
        rows = self.rows

        class Cursor:
            async def fetchall(self):
                return rows

        return Cursor()


class Graph:
    """A reader that answers with `reply`, or raises it; records what it was told and under which sources."""

    def __init__(self, reply):
        self.reply, self.asked = reply, []

    async def ainvoke(self, state, config=None):
        self.asked.append((state["messages"][0].content, run_sources.CURRENT.get(), PUBLIC_RUN.get()))
        if isinstance(self.reply, Exception):
            raise self.reply
        return {"messages": [HumanMessage("task"), AIMessage(self.reply), HumanMessage("after")]}


def proposal(work):
    return context.Current(id=1, title="t", org_id=7, org_name="SeSTA", funder_id=3, funder_name="ABF", work=work,
                           scope=CallerScope(UUID(int=5), False, {7: "admin"}), can_edit=True)


@pytest.fixture
def run(monkeypatch):
    store = {}

    def _setup(work, *, evidence="Found 3 facts.", funder="Found 1 fact.", public=None, rows=()):
        store["work"] = work
        graphs = NS(evidence=Graph(evidence), funder=Graph(funder), public=Graph(public) if public else None)
        monkeypatch.setattr(readers, "BUILT", readers._Built(evidence=graphs.evidence, funder=graphs.funder,
                                                             public=graphs.public, parallel=2, trace={}))
        monkeypatch.setattr(readers, "get_pool", lambda: FakePool(list(rows)))

        async def save(pool, proposal_id, change):
            store["work"] = change(store["work"], "t").work
            return store["work"]

        async def user_name(pool, user_id):
            return ADMIN

        monkeypatch.setattr(repo, "save", save)
        monkeypatch.setattr(repo, "user_name", user_name)
        return graphs

    return store, _setup


class TestRead:
    async def test_each_file_and_the_funder_are_read_and_marked(self, run):
        store, setup = run
        graphs = setup({"sources": [41]}, rows=[{"id": 41, "title": "Workplan", "link": False}])
        out = await readers.read(proposal({"sources": [41]}))
        assert out == "Workplan: read.\nFound 3 facts.\nwhat ABF looks for: read.\nFound 1 fact."
        held = store["work"]["readers"]
        assert held["41"]["status"] == "done" and held["funder"]["status"] == "done"
        assert held["41"]["title"] == "Workplan" and held["41"]["by"] == ADMIN
        task, sources, public = graphs.evidence.asked[0]
        assert task.startswith('Read document 41, "Workplan", for SeSTA\'s proposal to ABF.')
        assert sources.vault_docs == frozenset({41}) and public is None
        assert graphs.funder.asked[0][0].startswith("Read what Sangam holds on ABF")
        assert run_sources.CURRENT.get() is None  # each reader's sources are reset

    async def test_an_unreadable_file_fails_with_one_short_reason(self, run):
        store, setup = run
        setup({"sources": [41]}, evidence="UNREADABLE: It is a scan. Nothing to read.\nmore",
              rows=[{"id": 41, "title": None, "link": False}])
        out = await readers.read(proposal({"sources": [41]}))
        assert out.splitlines()[0] == "Untitled file: could not read it (It is a scan)."
        assert store["work"]["readers"]["41"] | {"status": "failed", "error": "It is a scan"} == \
            store["work"]["readers"]["41"]

    async def test_a_reader_that_raises_does_not_stop_the_others(self, run):
        store, setup = run
        setup({"sources": [41]}, evidence=RuntimeError("boom"), rows=[{"id": 41, "title": "W", "link": False}])
        out = await readers.read(proposal({"sources": [41]}))
        assert "W: could not read it (something went wrong while reading it)." in out
        assert store["work"]["readers"]["funder"]["status"] == "done"

    async def test_a_saved_link_is_not_read(self, run):
        store, setup = run
        graphs = setup({"sources": [41]}, rows=[{"id": 41, "title": "Site", "link": True}])
        out = await readers.read(proposal({"sources": [41]}))
        assert out.startswith("Site: could not read it (it is a link to a web page")
        assert graphs.evidence.asked == []
        assert store["work"]["readers"]["41"]["status"] == "failed"

    async def test_nothing_left_to_read(self, run):
        _, setup = run
        done = {"status": "done", "at": datetime.now(UTC).isoformat()}
        setup({"sources": [], "readers": {"funder": done}})
        assert (await readers.read(proposal({}))).startswith("Every ticked file has been read.")

    async def test_someone_else_reading_is_refused(self, run):
        _, setup = run
        busy = {"status": "running", "at": datetime.now(UTC).isoformat(), "by": {"name": "Ravi"}}
        setup({"sources": [], "readers": {"funder": busy}})
        assert await readers.read(proposal({})) == \
            "REFUSED: Ravi started reading the files 0 min ago; wait until they are read."

    async def test_public_research_without_a_key(self, run):
        _, setup = run
        setup({})
        assert (await readers.read(proposal({}), public=True)).startswith("Public research is not available")

    async def test_public_research_runs_alone_with_its_own_task(self, run, monkeypatch):
        store, setup = run
        graphs = setup({"sources": [41]}, public="Found 2 public facts.")

        async def facts(pool, owner, org_id):
            return NS(org=NS(district="Udalguri", state="Assam"), places=[], programs=[NS(name="Wells")],
                      tags=[NS(parent_label="Water", label="Wells"), NS(parent_label=None, label="Health")],
                      sdgs=[NS(code="6", label="Clean water")])

        monkeypatch.setattr(profile_facts, "org_facts", facts)
        out = await readers.read(proposal({"sources": [41]}), public=True)
        assert out == "Public research on the problem and place: read.\nFound 2 public facts."
        task, sources, public = graphs.public.asked[0]
        assert "Where it works: Udalguri, Assam" in task and "Its themes: Water › Wells; Health" in task
        assert "Its programmes: Wells" in task and "SDGs on record: 6 Clean water" in task
        assert sources.web and public.avoid == ("SeSTA",)
        assert graphs.evidence.asked == [] and list(store["work"]["readers"]) == ["public"]
        assert store["work"]["readers"]["public"]["unopened"] == []
        assert "summaries" not in store["work"]["readers"]["public"]
        assert "brief" not in store["work"]["readers"]["public"]  # no brief model in this setup

    async def test_the_brief_is_written_beside_the_search_without_the_org(self, run, monkeypatch):
        store, setup = run
        setup({}, public="Found 1 public fact.")
        asked = []

        async def write(task, model):
            asked.append((task, model))
            return "**A. Problem magnitude**"

        async def facts(pool, owner, org_id):
            return NS(org=NS(district="Udalguri", state="Assam"), places=[], programs=[NS(name="SeSTA wells")],
                      tags=[NS(parent_label=None, label="Livelihoods")], sdgs=[NS(code="1", label="No poverty")])

        monkeypatch.setattr(readers.BUILT, "brief", ("web model",))
        monkeypatch.setattr(readers.brief, "write", write)
        monkeypatch.setattr(profile_facts, "org_facts", facts)
        out = await readers.read(proposal({}), public=True)
        task, model = asked[0]
        assert model == ("web model",) and "Where the work happens: Udalguri, Assam" in task
        assert "Themes: Livelihoods" in task and "SDGs on record: 1 No poverty" in task
        assert "sesta" not in task.lower() and "Programmes: none on record" in task
        assert store["work"]["readers"]["public"]["brief"] == "**A. Problem magnitude**"
        assert out.endswith("The brief now on the Secondary research card:\n**A. Problem magnitude**")

    async def test_a_run_for_an_ask_carries_its_focus_and_records_what_it_added(self, run, monkeypatch):
        store, setup = run
        public = {"subject": "dropout, Udalguri", "value": "19.8%", "found_by": "public", "status": "proposed"}
        own = {"subject": "girls enrolled", "value": "412", "origin": "vault", "status": "confirmed"}
        graphs = setup({"facts": {"k1": public, "k2": own}, "research_asks": {"a1": {"kind": "chat"}}},
                       public="Found 1 more.")

        async def load(pool, proposal_id):
            facts = {**store["work"]["facts"], "k3": {**public, "subject": "dropout, Mazbat", "ask": "a2"}}
            return {"work": {**store["work"], "facts": facts}}

        async def facts(pool, owner, org_id):
            return None

        monkeypatch.setattr(repo, "load", load)
        monkeypatch.setattr(profile_facts, "org_facts", facts)
        ask = {"kind": "chat", "ask": "SHG credit", "focus": ["SHG credit linkage, Assam"], "sites": ["nrlm.gov.in"],
               "sections": []}
        p = proposal(store["work"])
        await readers.read(p, public=True, ask=ask)
        task, _, run_ = graphs.public.asked[0]
        assert run_.ask == "a2"
        assert "The person asked: SHG credit" in task and "Look into: SHG credit linkage, Assam" in task
        assert "Start on these sites: nrlm.gov.in" in task and "- dropout, Udalguri: 19.8%" in task
        assert "girls enrolled" not in task
        recorded = store["work"]["research_asks"]["a2"]
        assert recorded["status"] == "done" and recorded["added"] == 1 and recorded["focus"] == ask["focus"]

    async def test_a_failed_count_of_what_an_ask_added_still_marks_it_done(self, run, monkeypatch):
        store, setup = run
        setup({}, public="Found nothing.")

        async def load(pool, proposal_id):
            raise RuntimeError("db down")

        async def facts(pool, owner, org_id):
            return None

        monkeypatch.setattr(repo, "load", load)
        monkeypatch.setattr(profile_facts, "org_facts", facts)
        ask = {"kind": "chat", "ask": "SHG credit", "focus": [], "sites": [], "sections": []}
        await readers.read(proposal({}), public=True, ask=ask)
        assert store["work"]["readers"]["public"]["status"] == "done"
        assert store["work"]["research_asks"]["a1"] | {"status": "done", "added": 0} == store["work"]["research_asks"]["a1"]

    async def test_the_cards_search_is_marked_running_then_finishes_in_the_background(self, run, monkeypatch):
        store, setup = run
        setup({}, public="Found 1 public fact.")

        async def facts(pool, owner, org_id):
            return None

        monkeypatch.setattr(profile_facts, "org_facts", facts)
        await readers.search(proposal({}))
        assert store["work"]["readers"]["public"]["status"] == "running"
        await asyncio.gather(*readers._SEARCHES)
        assert store["work"]["readers"]["public"]["status"] == "done" and not readers._SEARCHES

    async def test_the_cards_search_without_a_key_or_while_running(self, run):
        _, setup = run
        setup({})
        with pytest.raises(LookupError):
            await readers.search(proposal({}))
        busy = {"status": "running", "at": datetime.now(UTC).isoformat(), "by": {"name": "Ravi"}}
        setup({"readers": {"public": busy}}, public="x")
        with pytest.raises(readers.Busy):
            await readers.search(proposal({}))


class TestPublicInputs:
    async def test_no_record_means_nothing_to_search_by(self, monkeypatch):
        async def none(pool, owner, org_id):
            return None

        monkeypatch.setattr(readers, "get_pool", lambda: None)
        monkeypatch.setattr(profile_facts, "org_facts", none)
        assert await readers._public_inputs(proposal({})) == ([], [], [], [])

    async def test_places_name_their_state_once(self, monkeypatch):
        async def facts(pool, owner, org_id):
            return NS(org=NS(district=None, state=None), programs=[], tags=[], sdgs=[],
                      places=[NS(name="Udalguri", state="Assam"), NS(name="Assam", state="Assam"),
                              NS(name="Delhi", state=None)])

        monkeypatch.setattr(readers, "get_pool", lambda: None)
        monkeypatch.setattr(profile_facts, "org_facts", facts)
        places, *_ = await readers._public_inputs(proposal({}))
        assert places == ["Udalguri, Assam", "Assam", "Delhi"]


def test_last_text_without_an_answer_is_empty():
    assert readers._last_text({"messages": [HumanMessage("hi")]}) == ""
    assert readers._last_text({}) == ""


def test_a_long_reason_is_cut():
    assert readers._reason("UNREADABLE: " + "x" * 400) == "x" * readers.ERROR_TEXT


async def test_no_ticked_files_needs_no_query(monkeypatch):
    def never():
        raise AssertionError("no query for no files")

    monkeypatch.setattr(readers, "get_pool", never)
    assert await readers._titles(7, []) == ({}, set())
