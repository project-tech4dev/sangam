"""Import's Doc Vault: who may read an org's files, what a save must cite, and what reaches the catalog."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated, ClassVar

import pytest
from deepagents import create_deep_agent
from deepagents.backends.state import StateBackend
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command

from app.agent.harness import filesystem
from app.core.security import CallerScope
from app.ingest import review, vault
from app.ingest.middleware import DropFilesOnExit
from app.ingest.research_records import VaultResearch
from app.ingest.tools import catalog_tools, vault_tools
from tests.test_import_roles import MEMBER, STAFF, STEWARD, _Conn, _Pool, running_as

DOC = vault.url(12)
OTHER = CallerScope(MEMBER.user_id, False, {9: "member"}, {9: "Kabil"})


def finding(concept: str = "rfp", doc: int = 12, marker: str | None = "p3", **extra) -> dict:
    mark = f"[vault:{doc}#{marker}] " if marker else ""
    return {"concept": concept, "source_url": vault.url(doc), "evidence": f"{mark}Applications open in May 2026.",
            **extra}


class TestCitations:
    def test_a_vault_url_names_its_document(self):
        assert vault.document_id(DOC) == 12 and vault.is_vault_url(DOC)
        assert vault.document_id("https://staff-sources.sangam.invalid/12") is None

    def test_markers_are_read_from_the_evidence(self):
        assert vault.marked_ids("[vault:12#p3] and [vault:4#Grants!B7]") == {12, 4}

    @pytest.mark.parametrize(("f", "problem"), [
        (finding(), None),
        (finding(doc=99), "not in this organisation's vault"),
        (finding(marker=None), "lacks its [vault:12#…] marker"),
        ({"concept": "rfp", "source_url": "https://example.org/a", "evidence": "x"}, "not a vault document URL"),
    ])
    def test_a_save_cites_this_vault_by_url_and_marker(self, f, problem):
        problems = vault.check_findings([f], {12})
        assert (problems == []) if problem is None else problem in problems[0]

    def test_pdf_pages_become_markers(self, monkeypatch):
        monkeypatch.setattr(vault, "extract_pdf_text", lambda path, s, e: ("--- page 3 ---\nGrant of 4 lakh", 5))
        text = vault.pdf_text({"id": 12, "title": "Sanction letter"}, b"%PDF", 3, 3)
        assert "[vault:12#p3]\nGrant of 4 lakh" in text and "--- page" not in text


class TestReadingTheVault:
    async def test_another_orgs_file_reads_as_missing(self, monkeypatch):
        async def doc(pool, doc_id):
            return {"id": doc_id, "org_id": 7, "storage_path": "org-vault/7/a.pdf"}

        monkeypatch.setattr(vault, "document", doc)
        monkeypatch.setattr(vault_tools, "get_pool", lambda: None)
        monkeypatch.setattr(vault, "read", lambda *a, **k: pytest.fail("read another org's file"))
        with running_as(OTHER):
            out = await vault_tools.read_vault_document.ainvoke({"document_id": 12})
        assert out == "No Doc Vault file 12 you can read."

    async def test_listing_needs_an_org_the_caller_reads(self, monkeypatch):
        monkeypatch.setattr(vault_tools, "get_pool", lambda: _Pool([{"id": 7, "name": "Arpan", "slug": "arpan"}]))
        with running_as(OTHER):
            out = await vault_tools.list_vault_documents.ainvoke({"org": "arpan"})
        assert out.startswith("No Doc Vault you can read")


class TestSavingVaultFindings:
    FUNDER: ClassVar[dict] = {"entity_name": "Acme Foundation", "entity_kind": "funder", "org_id": 7, "documents_read": [12],
              "findings": [{"concept": "rfp", "title": "Call 2026", "source_url": DOC, "confidence": "high",
                            "evidence": "[vault:12#p3] Acme's call for 2026 opens in May."}]}

    def _pool(self, monkeypatch, own: set[int]):
        pool = _Pool([{"id": 1}])

        async def in_vault(p, org_id, ids):
            return ids & own

        monkeypatch.setattr(vault, "in_vault", in_vault)
        monkeypatch.setattr(vault_tools, "get_pool", lambda: pool)
        return pool

    async def test_a_member_saves_from_its_own_vault(self, monkeypatch):
        pool = self._pool(monkeypatch, {12})
        with running_as(MEMBER):
            out = await vault_tools.save_vault_findings.ainvoke({"findings": self.FUNDER})
        assert out.startswith("Saved as vault_research #1 (acme-foundation)")
        assert any("ON CONFLICT (slug, researched_on, org_id)" in sql for sql in pool.conn.sql)

    async def test_citing_another_orgs_file_saves_nothing(self, monkeypatch):
        pool = self._pool(monkeypatch, set())
        with running_as(MEMBER):
            out = await vault_tools.save_vault_findings.ainvoke({"findings": self.FUNDER})
        assert out.startswith("REFUSED, nothing saved") and "document 12 is not in" in out
        assert not any("INSERT" in sql for sql in pool.conn.sql)

    async def test_another_orgs_vault_is_refused_before_the_database(self, monkeypatch):
        monkeypatch.setattr(vault_tools, "get_pool", lambda: pytest.fail("reached the database"))
        with running_as(OTHER):
            out = await vault_tools.save_vault_findings.ainvoke({"findings": self.FUNDER})
        assert out.startswith("REFUSED")

    async def test_an_ngo_from_the_vault_needs_its_steward(self, monkeypatch):
        monkeypatch.setattr(vault_tools, "get_pool", lambda: pytest.fail("reached the database"))
        ngo = {**self.FUNDER, "entity_name": "Arpan", "entity_kind": "org"}
        with running_as(MEMBER):
            out = await vault_tools.save_vault_findings.ainvoke({"findings": VaultResearch(**ngo)})
        assert "stewards" in out


class TestWhatReachesTheCatalog:
    def test_a_funders_general_facts_pass(self):
        kept, held = vault.hold_at_promote([finding("rfp"), finding("program")], "funder")
        assert len(kept) == 2 and held == []

    def test_the_orgs_own_facts_are_held_without_their_values(self):
        kept, held = vault.hold_at_promote([finding("csr_grant", amount="4 lakh")], "funder")
        assert kept == [] and "kept private" in held[0] and "lakh" not in held[0]

    def test_nothing_from_the_vault_reaches_an_ngo_record(self):
        kept, held = vault.hold_at_promote([finding("identity")], "org")
        assert kept == [] and "stay with it" in held[0]

    def test_an_unmarked_finding_is_held(self):
        kept, held = vault.hold_at_promote([finding(marker=None)], "funder")
        assert kept == [] and "marker" in held[0]

    def test_public_findings_are_untouched(self):
        public = {"concept": "csr_grant", "source_url": "https://example.org/a", "evidence": "x"}
        assert vault.hold_at_promote([public], "funder") == ([public], [])


class _Routed(_Conn):
    """Vault rows for the vault query, the research row for everything else."""

    def __init__(self, research, vaults):
        super().__init__([])
        self.research, self.vaults = research, vaults

    async def execute(self, sql, params=()):
        rows = self.vaults if "vault_research" in sql else self.research

        async def all_():
            return rows

        return SimpleNamespace(fetchall=all_)


class _RoutedPool(_Pool):
    def __init__(self, research, vaults):
        self.conn = _Routed(research, vaults)


RESEARCH = {"slug": "acme-foundation", "entity_name": "Acme Foundation", "entity_kind": "funder",
            "findings": [{"concept": "rfp", "source_url": "https://example.org/a", "evidence": "public"},
                         finding("csr_grant", doc=55)]}  # a vault URL in the shared row was never checked
VAULTS = [{"org_id": 7, "findings": [finding("rfp")], "documents_read": [12], "titles": {"12": "Grant letter"}},
          {"org_id": 9, "findings": [finding("program", doc=40)], "documents_read": [40], "titles": {}}]


class TestTheVaultJoinsTheResearch:
    async def _rows(self, scope, vault_on=True):
        pool = _RoutedPool([dict(RESEARCH)], VAULTS)
        return (await catalog_tools._research_rows(pool, "acme-foundation", scope, vault=vault_on))[0]

    async def test_a_member_gets_its_own_orgs_findings_only(self):
        row = await self._rows(MEMBER)
        assert [vault.document_id(f["source_url"]) for f in row["findings"]] == [None, 12]
        assert row["vault"] == [{"org_id": 7, "documents_read": [12], "titles": {"12": "Grant letter"}}]

    async def test_staff_get_every_orgs(self):
        row = await self._rows(STAFF)
        assert {f["source_url"] for f in row["findings"]} >= {vault.url(12), vault.url(40)}

    async def test_a_steward_gets_each_supported_orgs(self):
        assert len((await self._rows(STEWARD))["vault"]) == 1  # supports 7 and 8; 9 is not its

    async def test_tools_that_brief_researchers_get_none(self):
        row = await self._rows(STAFF, vault_on=False)
        assert [f["source_url"] for f in row["findings"]] == ["https://example.org/a"]

    async def test_review_names_the_file_and_marks_held_findings(self):
        row = await self._rows(MEMBER)
        rfp, = [a for a in review.answers(row) if a["private"]]
        assert rfp["source_name"] == "Grant letter" and not rfp["held"]
        row["findings"].append(finding("csr_grant"))
        held = [a for a in review.answers(row) if a["concept"] == "csr_grant"]
        assert held[0]["held"] and held[0]["source_name"] == "Grant letter"


class TestTheReaderLeavesNoFiles:
    async def test_every_file_is_deleted_on_exit(self):
        state = {"files": {"/large_tool_results/abc": {"content": ["vault text"]}}}
        assert await DropFilesOnExit().aafter_agent(state, None) == {"files": {"/large_tool_results/abc": None}}
        assert DropFilesOnExit().after_agent({"files": {}}, None) is None

    async def test_through_deepagents_the_parent_gets_none_and_keeps_its_own(self):
        """A subagent's files merge back into its parent; this pins that the reader's do not."""
        def file(text):
            return {"content": [text], "created_at": "2026-10-10", "modified_at": "2026-10-10"}

        @tool
        def evicted(tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
            """Leaves a file in state, as an eviction would."""
            return Command(update={"files": {"/large_tool_results/vault": file("vault text")},
                                   "messages": [ToolMessage("ok", tool_call_id=tool_call_id)]})

        class Fake(GenericFakeChatModel):
            def bind_tools(self, tools, **kw):
                return self

        def says(*msgs):
            return Fake(messages=iter(msgs))

        reader = {"name": "vault-reader", "description": "r", "system_prompt": "r", "tools": [evicted],
                  "middleware": [filesystem(StateBackend(), evict=False), DropFilesOnExit()],
                  "model": says(AIMessage("", tool_calls=[{"name": "evicted", "args": {}, "id": "e"}]),
                                AIMessage("done"))}
        task = {"name": "task", "args": {"description": "read", "subagent_type": "vault-reader"}, "id": "t"}
        parent = create_deep_agent(model=says(AIMessage("", tool_calls=[task]), AIMessage("fin")),
                                   tools=[], subagents=[reader])
        out = await parent.ainvoke({"messages": [{"role": "user", "content": "go"}],
                                    "files": {"/large_tool_results/web": file("web page")}})
        assert sorted(out["files"]) == ["/large_tool_results/web"]


@pytest.mark.integration
class TestTheVaultTable:
    async def test_one_row_per_entity_day_and_org(self, db):
        cols = await (await db.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'vault_research'::regclass AND contype = 'u'"
        )).fetchall()
        assert cols
        rls = await (await db.execute(
            "SELECT relrowsecurity FROM pg_class WHERE relname = 'vault_research'")).fetchone()
        assert rls[0] if isinstance(rls, tuple) else rls["relrowsecurity"]

    async def test_a_stranger_lists_no_private_document(self, db):
        from uuid import uuid4

        from app.repositories import documents
        from tests.test_storage import _PoolOf

        rows, _ = await documents.list_documents(_PoolOf(db), limit=500, offset=0, user_id=uuid4())
        ids = [r["id"] for r in rows]
        private = await (await db.execute(
            "SELECT count(*) AS n FROM documents WHERE id = ANY(%s) AND NOT is_public", (ids,))).fetchone()
        assert (private["n"] if isinstance(private, dict) else private[0]) == 0

    async def test_the_vault_queries_run(self, db):
        from tests.test_storage import _PoolOf

        pool = _PoolOf(db)
        row = {"slug": "no-such-funder", "entity_name": "No Such Funder", "findings": []}
        assert await catalog_tools._with_vault(pool, row, STAFF) == row
        assert await vault.in_vault(pool, 1, {1}) <= {1}
        assert isinstance(await vault.documents(pool, 1), list)

    async def test_a_save_upserts_once_per_day(self, db, monkeypatch):
        from tests.test_storage import _PoolOf

        org = await (await db.execute("SELECT id FROM orgs ORDER BY id LIMIT 1")).fetchone()
        if org is None:
            pytest.skip("no org seeded")
        org_id = org["id"] if isinstance(org, dict) else org[0]
        monkeypatch.setattr(vault_tools, "get_pool", lambda: _PoolOf(db))
        save = {"entity_name": "Zz Vault Test Funder", "entity_kind": "funder", "org_id": org_id,
                "documents_read": [], "findings": []}
        try:
            with running_as(STAFF):
                for _ in range(2):
                    out = await vault_tools.save_vault_findings.ainvoke({"findings": save})
                    assert out.startswith("Saved as vault_research"), out
            n = await (await db.execute(
                "SELECT count(*) AS n FROM vault_research WHERE slug = 'zz-vault-test-funder'")).fetchone()
            assert (n["n"] if isinstance(n, dict) else n[0]) == 1
            row = {"slug": "zz-vault-test-funder", "entity_name": "Zz Vault Test Funder", "findings": []}
            assert (await catalog_tools._with_vault(_PoolOf(db), row, STAFF))["vault"][0]["org_id"] == org_id
        finally:
            await db.execute("DELETE FROM vault_research WHERE slug = 'zz-vault-test-funder'")
