"""context: the run's proposal read fresh, and the words the live block uses for log entries, questions and readers."""

from uuid import UUID

import pytest

from app.core.security import CallerScope, chat_proposal, chat_scope
from app.proposals import context
from app.repositories import proposals as repo

ME = str(UUID(int=5))
SCOPE = CallerScope(UUID(int=5), False, {7: "member"})


def current(work):
    return context.Current(id=1, title="t", org_id=7, org_name="SeSTA", funder_id=3, funder_name="ABF", work=work,
                           scope=SCOPE, can_edit=True)


async def in_chat(proposal_id, scope):
    """context.current() with the chat's proposal and scope set, reset in the same task."""
    tokens = chat_proposal.set(proposal_id), chat_scope.set(scope)
    try:
        return await context.current()
    finally:
        chat_proposal.reset(tokens[0])
        chat_scope.reset(tokens[1])


class TestCurrent:
    async def test_no_proposal_in_this_chat(self):
        assert await in_chat(None, SCOPE) is None
        assert await in_chat(1, None) is None

    async def test_a_proposal_gone_since(self, monkeypatch):
        async def load(pool, proposal_id):
            return None

        monkeypatch.setattr(context, "get_pool", lambda: None)
        monkeypatch.setattr(repo, "load", load)
        assert await in_chat(1, SCOPE) is None

    async def test_it_is_read_with_the_callers_rights(self, monkeypatch):
        async def load(pool, proposal_id):
            return {"id": proposal_id, "title": "t", "org_id": 7, "org_name": "SeSTA", "funder_id": 3,
                    "funder_name": "ABF", "work": None}

        monkeypatch.setattr(context, "get_pool", lambda: None)
        monkeypatch.setattr(repo, "load", load)
        p = await in_chat(9, SCOPE)
        assert (p.id, p.work, p.can_edit) == (9, {}, False)  # a member reads only


def test_a_form_without_a_document_id():
    assert context.form({"template": {"url": "https://x"}}) == "the funder's own form"
    assert context.form({"template": {"document_id": 4}}) == "the funder's own form (document 4)"
    assert context.form({}) == "not chosen yet"


@pytest.mark.parametrize("raw", ['{"part": "A3"}', {"part": "A3"}])
def test_the_screen_is_read_as_json_or_a_dict(raw):
    state = {"ag-ui": {"context": [{"description": "other", "value": "{}"},
                                   {"description": context.SCREEN, "value": raw}]}}
    assert context.screen_part({}, state) == "A3"


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", None])
def test_a_screen_that_is_not_an_object_is_empty(raw):
    state = {"ag-ui": {"context": [{"description": context.SCREEN, "value": raw}]}}
    assert context._screen(state) == {}


def test_the_screen_may_come_as_objects():
    class Item:
        description, value = context.SCREEN, {"part": "Z9", "step": 3}

    class Ui:
        context = [Item()]

    state = {"ag-ui": Ui()}
    assert context._screen(state) == {"part": "Z9", "step": 3}
    assert context.screen_part({}, state) is None  # a code the server does not know
    assert context.on_screen(current({}), state) == "On screen now: step 3. No part is open."
    assert context.on_screen(current({}), {}) == "On screen now: not known."


WORK = {
    "requirements": [{"key": "12a", "label": "12A registration"}],
    "facts": {"k1": {"subject": "villages"}},
    "questions": {"q1": {"subject": "causes"}},
}


@pytest.mark.parametrize("entry, words", [
    ({"path": "sections.A3.done"}, "Problem and baseline [A3] (marked finished or not)"),
    ({"path": "sections.A3.text"}, "Problem and baseline [A3]"),
    ({"path": "sections.X1.score"}, "X1 [X1] (its score)"),
    ({"path": "gates.12a"}, "12A registration"),
    ({"path": "gates.zz"}, "a requirement"),
    ({"path": "facts.k1.status", "to": "confirmed"}, "villages (set to confirmed)"),
    ({"path": "facts.k1.used_in"}, "where villages is cited"),
    ({"path": "facts.k9"}, "a fact (added)"),
    ({"path": "questions.q1.status"}, "the question about causes"),
    ({"path": "readers.41", "to": "Workplan: done"}, "the reading of Workplan (done)"),
    ({"path": "readers.41", "to": None}, "the reading of a file ()"),
    ({"path": "versions", "to": 2}, "the saved Word files (2)"),
    ({"path": "style"}, "the writing style"),
    ({"path": "mystery"}, "mystery"),
])
def test_a_log_entry_in_words(entry, words):
    assert context._what(WORK, entry) == words


def test_waiting_names_who_was_asked_and_counts_unchecked_facts():
    work = {"facts": {"k1": {"status": "proposed"}, "k2": {"status": "proposed"}, "k3": {"status": "confirmed"}},
            "questions": {
                "q1": {"status": "open", "section": "A3", "subject": "causes", "asked_of": {"id": ME}},
                "q2": {"status": "open", "section": "Z", "subject": "budget", "asked_of": {"id": "x", "name": "Ravi"}},
                "q3": {"status": "open", "subject": "staff", "asked_of": None},
                "q4": {"status": "parked", "section": "A3", "subject": "baseline"},
                "q5": {"status": "answered", "subject": "done"}}}
    assert context.waiting(current(work)) == [
        "- q1 Problem and baseline, causes: asked of this person, waiting for their answer",
        "- q2 the proposal, budget: asked of Ravi, waiting; do not ask it again",
        "- q3 the proposal, staff: asked of a teammate, waiting; do not ask it again",
        ("- q4 Problem and baseline, baseline: saved for later by whoever was asked; ask it of this person only "
         "while Problem and baseline is the part open on their screen"),
        "- 2 facts not yet confirmed by anyone",
    ]
    assert context.waiting(current({"facts": {"k1": {"status": "proposed"}}})) == \
        ["- 1 fact not yet confirmed by anyone"]


def test_each_readers_outcome():
    work = {"readers": {"41": {"status": "done", "title": "Workplan"},
                        "42": {"status": "running", "by": {"name": "Ravi"}},
                        "43": {"status": "running"},
                        "44": {"status": "failed", "title": "Scan", "error": "no text"},
                        "45": {"status": "failed"},
                        "46": {"status": "odd"}}}
    assert context.reading(work) == [
        "- Workplan: read", "- a file: being read, started by Ravi", "- a file: being read, started by a teammate",
        "- Scan: could not be read: no text", "- a file: could not be read: no reason given", "- a file: odd"]


def test_the_live_block_lists_rewrites_files_fixes_and_a_long_selection():
    work = {"stage": 3, "sections": {"A3": {"text": "x", "needs_rewrite": True}},
            "readers": {"41": {"status": "done", "title": "Workplan"}},
            "requirements": [{"key": "12a", "label": "12A", "hard": True}], "gates": {"12a": "no"}}
    state = {"ag-ui": {"context": [{"description": context.SCREEN,
                                    "value": {"selection": "word  " * 200}}]}}
    block = context.live(current(work), state)
    assert "Marked NEEDS REWRITING, because a fact it cites was corrected or set aside: Problem and baseline [A3]." \
        in block
    assert "Files read for this proposal:\n- Workplan: read" in block
    assert "Still to fix before sending: " in block
    assert "Nothing stops this step being left." in block
    assert block.endswith('…"') and len(block.split('Selected text: "')[1]) == context.SCREEN_TEXT + 2


def test_a_reader_is_told_they_can_only_read():
    p = context.Current(**{**vars(current({"stage": 4})), "can_edit": False})
    block = context.live(p, {})
    assert "The person can only read this proposal." in block
    assert "To leave this step: this is the last step." in block
    assert block.endswith("Waiting:\n- nothing")
