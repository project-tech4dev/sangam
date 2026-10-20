"""add_facts' refusals and ask_user's whole round trip, with the interrupt and the reply sorter faked."""

from types import SimpleNamespace as NS
from uuid import UUID

import pytest
from langgraph.errors import GraphInterrupt

from app.core.security import CallerScope
from app.ingest import run_sources
from app.proposals import context
from app.proposals import facts as fact_rules
from app.proposals import questions as question_rules
from app.proposals.tools import ledger_tools as lt
from app.repositories import proposals as repo

ME = {"id": str(UUID(int=5)), "name": "Asha"}
RAVI = {"id": str(UUID(int=6)), "name": "Ravi"}
CAUSES = "The causes the project will act on"


def work(**kw):
    return {"stage": 3, "facts": {}, "questions": {}, "sources": [41], **kw}


def proposal(w, can_edit=True):
    return context.Current(id=1, title="t", org_id=7, org_name="SeSTA", funder_id=3, funder_name="ABF", work=w,
                           scope=CallerScope(UUID(int=5), False, {7: "admin"}), can_edit=can_edit)


def runtime(part="A3"):
    screen = {"ag-ui": {"context": [{"description": context.SCREEN, "value": {"part": part}}]}}
    return NS(state=screen, tool_call_id="call-1")


@pytest.fixture
def held(monkeypatch):
    """The proposal row: p.work is what the tool reads, store['work'] what the locked save sees."""
    store = {}

    def _open(w, *, stored=None, can_edit=True, saved=True):
        store["work"] = stored if stored is not None else w
        store["saves"] = 0
        p = proposal(w, can_edit)

        async def current():
            return p

        async def save(pool, proposal_id, change):
            store["saves"] += 1
            if not saved:
                return None
            applied = change(store["work"], "t")
            store["work"] = applied.work
            return applied

        async def user_name(pool, user_id):
            return ME

        monkeypatch.setattr(context, "current", current)
        monkeypatch.setattr(lt, "get_pool", lambda: None)
        monkeypatch.setattr(repo, "save", save)
        monkeypatch.setattr(repo, "user_name", user_name)
        return store

    return _open


DERIVED = {"subject": "share", "value": "10%", "origin": "derived", "section": "A3", "derived_from": ["k1"]}


class TestAddFacts:
    async def test_no_proposal_a_reader_and_too_early(self, held, monkeypatch):
        held(work(), can_edit=False)
        assert (await lt.add_facts.ainvoke({"facts": []})).startswith("REFUSED: you can read")
        held(work(stage=1))
        assert (await lt.add_facts.ainvoke({"facts": []})).startswith("REFUSED: add_facts is used from step 2")

        async def none():
            return None

        monkeypatch.setattr(context, "current", none)
        assert await lt.add_facts.ainvoke({"facts": []}) == lt.NO_PROPOSAL

    async def test_nothing_given(self, held):
        held(work())
        assert await lt.add_facts.ainvoke({"facts": []}) == "No facts given."

    async def test_every_fact_refused_writes_nothing(self, held):
        store = held(work())
        out = await lt.add_facts.ainvoke({"facts": [{**DERIVED, "derived_from": ["k9"]}]})
        assert out == "REFUSED share: a derived fact names the facts it is worked out from"
        assert store["saves"] == 0

    async def test_the_element_is_stored_in_the_sections_own_words(self, held):
        base = {"k1": {**fact_rules.make({"subject": "people", "value": "100", "origin": "derived",
                                          "from": ["k0"]}), "status": "confirmed"}}
        store = held(work(facts=base))
        out = await lt.add_facts.ainvoke({"facts": [{**DERIVED, "element": CAUSES.upper()}]})
        assert out == "k2 added: share = 10% (amber)"
        assert store["work"]["facts"]["k2"]["element"] == CAUSES

    async def test_a_proposal_gone_while_saving(self, held):
        held(work(facts={"k1": {"status": "confirmed"}}), saved=False)
        assert await lt.add_facts.ainvoke({"facts": [DERIVED]}) == lt.NO_PROPOSAL

    async def test_a_file_reader_cites_only_its_own_file(self, held, monkeypatch):
        held(work(sources=[41, 42]))
        monkeypatch.setattr(fact_rules, "problem", lambda w, f: None)
        token = run_sources.CURRENT.set(run_sources.Sources(web=False, vault_org=7, vault_docs=frozenset({41})))
        try:
            out = await lt.add_facts.ainvoke({"facts": [{"subject": "wells", "value": "40", "origin": "vault",
                                                         "document_id": 42}]})
        finally:
            run_sources.CURRENT.reset(token)
        assert out == "REFUSED wells: this reader may cite only the file it was given"

    async def test_a_failure_is_returned(self, held, monkeypatch):
        held(work())

        def boom(w, f):
            raise TypeError

        monkeypatch.setattr(fact_rules, "problem", boom)
        assert await lt.add_facts.ainvoke({"facts": [DERIVED]}) == "add_facts failed: TypeError"


def ask(**kw):
    return {"reason": "missing", "section": "A3", "subject": "causes", "found": "a survey [org:7]",
            "missing": "the causes ⟦k1⟧", "why": "funders fund causes", "element": CAUSES.lower(), **kw}


@pytest.fixture
def reply(monkeypatch):
    def _reply(value, kind=None):
        seen = {}

        def interrupt(card):
            seen["card"] = card
            return value

        async def classify(text, question, model):
            seen["classified"] = text
            return kind

        monkeypatch.setattr(lt, "interrupt", interrupt)
        monkeypatch.setattr(lt, "resolve_model", lambda name: None)
        if kind is not None:
            monkeypatch.setattr(question_rules, "classify", classify)
        return seen

    return _reply


async def call(**kw):
    return await lt.ask_user.coroutine(runtime=kw.pop("runtime", runtime()), **ask(**kw))


class TestAskUser:
    async def test_a_picked_answer_becomes_a_fact_the_person_said(self, held, reply):
        store = held(work())
        seen = reply({"kind": "pick", "choice": "Debt and drought"})
        out = await call(options=["Debt and drought", "  ", "b", "c", "d", "e"])
        assert out == ("ANSWERED: Asha said 'Debt and drought' about causes. Stored as k1, a fact they said.")
        card = seen["card"]
        assert card["found"] == "a survey" and card["missing"] == "the causes"
        assert card["options"] == ["Debt and drought", "b", "c", "d"]
        assert card | {"type": lt.QUESTION, "id": "q1", "ask": "call-1", "part": "Problem and baseline"} == card
        q = store["work"]["questions"]["q1"]
        assert q["status"] == "answered" and q["answer"] == "k1" and q["element"] == CAUSES
        assert store["work"]["facts"]["k1"]["origin"] == "you_said"

    async def test_later_parks_it(self, held, reply):
        store = held(work())
        reply({"kind": "pick", "choice": "Later"})
        out = await call()
        assert out.startswith("PARKED: Asha will answer about causes later.")
        assert store["work"]["questions"]["q1"] | {"status": "parked", "asked_of": None} == \
            store["work"]["questions"]["q1"]

    async def test_a_typed_question_back(self, held, reply):
        held(work())
        seen = reply({"kind": "text", "text": " what do you mean? "}, kind="question")
        out = await call()
        assert out.startswith("QUESTION BACK: the person asked: 'what do you mean?'")
        assert seen["classified"] == "what do you mean?"

    async def test_a_plain_string_reply_is_typed_text(self, held, reply):
        store = held(work())
        reply("Debt", kind="answer")
        assert (await call()).startswith("ANSWERED: Asha said 'Debt'")
        assert store["work"]["facts"]["k1"]["value"] == "Debt"

    async def test_not_about_the_part_on_screen(self, held, reply):
        store = held(work())
        reply(None)
        assert await call(runtime=runtime("A2")) == "REFUSED: ask only about the part the person has open on screen."
        assert store["saves"] == 0

    async def test_a_parked_gap_a_fact_now_fills_is_closed(self, held, reply):
        filled = fact_rules.make({"subject": "causes", "value": "debt", "origin": "derived", "from": ["k0"],
                                  "section": "A3", "element": CAUSES})
        parked = {"reason": "missing", "section": "A3", "element": CAUSES, "subject": "causes", "status": "parked",
                  "asked_of": None}
        store = held(work(facts={"k1": filled}, questions={"q1": parked}))
        reply(None)
        assert await call() == "REFUSED: already answered by k1."
        assert store["work"]["questions"]["q1"]["status"] == "closed"

    async def test_a_teammates_question_landing_first_is_refused(self, held, reply):
        theirs = {"reason": "missing", "section": "A3", "element": CAUSES, "subject": "causes", "status": "open",
                  "asked_of": RAVI}
        held(work(), stored=work(questions={"q1": theirs}))
        reply(None)
        assert await call() == "REFUSED: Ravi was asked this and has not answered yet; ask about something else."

    async def test_a_resumed_run_finds_its_question_already_open(self, held, reply):
        mine = {"reason": "missing", "section": "A3", "element": CAUSES, "subject": "causes", "status": "open",
                "asked_of": ME}
        store = held(work(questions={"q1": mine}))
        seen = reply({"kind": "pick", "choice": "Debt"})
        assert (await call()).startswith("ANSWERED")
        assert seen["card"]["id"] == "q1"
        assert store["work"]["questions"]["q1"]["status"] == "answered"

    async def test_the_pause_itself_is_not_swallowed(self, held, monkeypatch):
        held(work())

        def interrupt(card):
            raise GraphInterrupt(())

        monkeypatch.setattr(lt, "interrupt", interrupt)
        with pytest.raises(GraphInterrupt):
            await call()

    async def test_no_proposal_a_reader_and_a_failure(self, held, monkeypatch):
        held(work(), can_edit=False)
        assert (await call()).startswith("REFUSED: you can read")

        async def none():
            return None

        monkeypatch.setattr(context, "current", none)
        assert await call() == lt.NO_PROPOSAL

        async def boom():
            raise OSError

        monkeypatch.setattr(context, "current", boom)
        assert await call() == "ask_user failed: OSError"


@pytest.mark.parametrize("raw, out", [
    ({"kind": "pick", "choice": " later "}, ("skip", "later")),
    ({"kind": "pick", "choice": None}, ("answer", "")),
    ({"kind": "text"}, ("text", "")),
    (None, ("text", "")),
])
def test_reply_shapes(raw, out):
    assert lt._reply(raw) == out
