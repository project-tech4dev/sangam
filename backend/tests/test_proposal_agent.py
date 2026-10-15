"""The proposal agent's code-only safeguards: who may run its chat, what its tools refuse, what it is told."""

from uuid import UUID

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from app.core import security
from app.core.config import Settings
from app.core.security import CallerScope, CurrentUser, get_current_user, get_principal, proposal_chat_access
from app.proposals import context
from app.proposals.tools import proposal_tools
from app.repositories import proposals as repo
from tests.conftest import make_app

ME = CurrentUser(id=UUID(int=5), is_staff=False)
TEAMMATE = CurrentUser(id=UUID(int=6), is_staff=False)
ORG = 7


def client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def proposal(monkeypatch):
    """Proposal 1 in org ORG; tests set the caller's role, and claimed threads are kept as a dict."""
    state = {"role": "admin", "owners": {}}

    async def org_of(pool, proposal_id):
        return ORG if proposal_id == 1 else None

    async def memberships(pool, user_id):
        return [{"org_id": ORG, "role": state["role"], "org_name": "Seven"}] if state["role"] else []

    async def claim(pool, *, thread_id, user_id, title=None, use_case="ask", org_id=None):
        return state["owners"].setdefault(thread_id, user_id)

    monkeypatch.setattr(repo, "org_of", org_of)
    monkeypatch.setattr(security.threads, "claim_thread", claim)
    monkeypatch.setattr(security.me_repo, "list_memberships", memberships)
    return state


def proposal_app(who: CurrentUser = ME) -> FastAPI:
    app = make_app()

    @app.post("/proposal", dependencies=[Depends(proposal_chat_access)])
    async def run_agent():
        return StreamingResponse(iter([str(security.chat_proposal.get())]))

    app.dependency_overrides[get_principal] = lambda: who
    app.dependency_overrides[get_current_user] = lambda: who.id
    return app


async def post(thread_id: str = f"proposal-1-{ME.id}", who: CurrentUser = ME) -> httpx.Response:
    async with client(proposal_app(who)) as c:
        return await c.post("/proposal", json={"threadId": thread_id, "runId": "r1", "messages": []})


class TestWhoRunsTheChat:
    @pytest.mark.parametrize("role", ["admin", "steward"])
    async def test_an_editor_runs_their_own_chat_on_the_proposal(self, proposal, role):
        proposal["role"] = role
        response = await post()
        assert response.status_code == 200
        assert response.text == "1"

    async def test_a_member_may_not_run_it(self, proposal):
        proposal["role"] = "member"
        assert (await post()).status_code == 403

    async def test_a_stranger_does_not_learn_it_exists(self, proposal):
        proposal["role"] = None
        assert (await post()).status_code == 404

    @pytest.mark.parametrize("thread", ["import-x", "proposal-1", f"proposal-2-{ME.id}"])
    async def test_a_thread_that_is_not_your_chat_on_a_proposal_is_404(self, proposal, thread):
        assert (await post(thread)).status_code == 404

    async def test_two_editors_get_two_chats_and_neither_opens_the_others(self, proposal):
        assert (await post()).status_code == 200
        assert (await post(f"proposal-1-{TEAMMATE.id}", who=TEAMMATE)).status_code == 200
        assert proposal["owners"] == {f"proposal-1-{ME.id}": ME.id, f"proposal-1-{TEAMMATE.id}": TEAMMATE.id}
        assert (await post(f"proposal-1-{TEAMMATE.id}")).status_code == 404


def current(*, can_edit: bool, stage: int = 1, gates: dict | None = None) -> context.Current:
    work = {"stage": stage, "gates": gates or {},
            "requirements": [{"key": "fcra", "label": "FCRA registration", "hard": True}],
            "sections": {"A3": {"text": "Private draft about the block's wells", "rev": 1}},
            "match": {"id": 9, "score": 71}}
    scope = CallerScope(UUID(int=5), False, {ORG: "admin" if can_edit else "member"})
    return context.Current(id=1, title="SeSTA to ABF", org_id=ORG, org_name="SeSTA", funder_id=3,
                           funder_name="Axis Bank Foundation", work=work, scope=scope, can_edit=can_edit)


class TestToolsThatChange:
    async def test_advance_step_refuses_a_reader_before_touching_the_proposal(self, monkeypatch):
        async def read_only():
            return current(can_edit=False)

        async def never(*args, **kwargs):
            raise AssertionError("a reader's call reached the database")

        monkeypatch.setattr(context, "current", read_only)
        monkeypatch.setattr(repo, "save", never)
        assert (await proposal_tools.advance_step.ainvoke({})) == proposal_tools.READ_ONLY

    async def test_advance_step_says_what_is_missing(self, monkeypatch):
        async def editor():
            return current(can_edit=True)

        async def save(pool, proposal_id, change):
            return change(current(can_edit=True).work, "SeSTA to ABF")

        async def user_name(pool, user_id):
            return {"id": None, "name": "Asha"}

        monkeypatch.setattr(context, "current", editor)
        monkeypatch.setattr(proposal_tools, "get_pool", lambda: None)
        monkeypatch.setattr(repo, "save", save)
        monkeypatch.setattr(repo, "user_name", user_name)
        assert await proposal_tools.advance_step.ainvoke({}) == "NOT YET: to leave this step, answer FCRA registration."


class TestWhatTheModelIsTold:
    def test_the_stable_block_is_the_same_for_the_same_proposal(self):
        assert context.stable(current(can_edit=True)) == context.stable(current(can_edit=True))

    def test_the_stable_block_holds_no_written_text(self):
        block = context.stable(current(can_edit=True))
        assert "wells" not in block
        assert "Problem and baseline [A3]: draft" in block

    def test_the_live_block_carries_the_screen_and_the_reader(self):
        screen = {"ag-ui": {"context": [{"description": context.SCREEN,
                                         "value": '{"step": "Can you apply?", "selection": "baseline  of 2019"}'}]}}
        block = context.live(current(can_edit=False), screen)
        assert "can only read this proposal" in block
        assert "To leave this step: answer FCRA registration." in block
        assert "On screen now: step Can you apply?. No part is open." in block
        assert 'Selected text: "baseline of 2019"' in block

    def test_only_anthropic_gets_the_cache_breakpoint(self):
        from app.proposals.middleware import with_blocks

        cached = with_blocks(None, "stable", "live", True).content_blocks
        assert cached[0].get("cache_control") == {"type": "ephemeral"}
        assert "cache_control" not in cached[1]
        assert "cache_control" not in with_blocks(None, "stable", "live", False).content_blocks[0]

    def test_the_live_block_names_teammates_changes_not_your_own(self):
        p = current(can_edit=True)
        p.work["log"] = [
            {"at": "2026-10-15T09:00:00+00:00", "by": {"id": str(TEAMMATE.id), "name": "Ravi"}, "path": "gates.fcra"},
            {"at": "2026-10-15T10:00:00+00:00", "by": {"id": str(ME.id), "name": "Asha"}, "path": "sections.A3.text"},
        ]
        block = context.live(p, {})
        assert "- Ravi changed FCRA registration, 2026-10-15 09:00 UTC" in block
        assert "Asha" not in block


def test_the_agent_has_its_seven_tools_and_read_file_only():
    from langgraph.checkpoint.memory import InMemorySaver

    from app.proposals.agent import build_proposal_agent

    graph = build_proposal_agent(Settings(), InMemorySaver())
    assert sorted(graph.nodes["tools"].bound.tools_by_name) == [
        "add_facts", "advance_step", "ask_user", "read_file", "read_files", "read_match", "read_org_record",
        "read_proposal"]


async def test_a_local_test_sign_in_is_refused_once_supabase_is_on(monkeypatch):
    settings = Settings(supabase_url="https://proj.supabase.co", dev_auth=True)
    monkeypatch.setattr(security, "get_settings", lambda: settings)

    async def verify(token, url):
        raise security.jwt.InvalidTokenError("not a Supabase token")

    monkeypatch.setattr(security, "verify_token", verify)
    with pytest.raises(HTTPException) as refused:
        await security.resolve_principal("Bearer dev:admin@local.test")
    assert refused.value.status_code == 401
