"""Sangam's library and an org's Doc Vault, as Import's researchers and vault-reader see them."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

from app.ingest import run_sources, vault
from app.ingest.matcher import Match
from app.ingest.run_sources import Sources
from app.ingest.tools import library_tools, vault_tools
from tests.cov_ingest_fakes import BrokenPool, ScriptConn, ScriptPool, running_as
from tests.test_import_roles import MEMBER, STAFF, STEWARD

ARCHIVED = "source-archive/abc/def-report.pdf"


def matches(monkeypatch, funder: Match, org: Match) -> None:
    async def rf(conn, name):
        return funder

    async def ro(conn, name):
        return org
    monkeypatch.setattr(library_tools, "resolve_funder", rf)
    monkeypatch.setattr(library_tools, "resolve_org", ro)


class TestListLibrary:
    async def test_an_unresolved_name_has_nothing_filed(self, monkeypatch):
        matches(monkeypatch, Match("new"), Match("close", 3))
        monkeypatch.setattr(library_tools, "get_pool", lambda: ScriptPool())
        out = await library_tools.list_library_documents.ainvoke({"name": "Acme"})
        assert out == "Sangam's library has nothing filed under 'Acme'."

    async def test_a_resolved_name_with_no_documents(self, monkeypatch):
        matches(monkeypatch, Match("exact", 4), Match("new"))
        pool = ScriptPool()
        monkeypatch.setattr(library_tools, "get_pool", lambda: pool)
        out = await library_tools.list_library_documents.ainvoke({"name": "Acme"})
        assert out == "Sangam's library holds no documents for 'Acme'."
        assert pool.conn.calls[0][1] == (4, None)

    async def test_lists_what_can_be_read_and_what_is_a_link(self, monkeypatch):
        matches(monkeypatch, Match("alias", 4), Match("exact", 9))
        rows = [
            {"id": 1, "title": "Annual report", "doc_type": "annual_report", "as_of": "2025-03-31",
             "source_url": "https://acme.org/ar.pdf", "storage_path": ARCHIVED},
            {"id": 2, "title": None, "doc_type": None, "as_of": None, "source_url": "https://acme.org/csr",
             "storage_path": None},
        ]
        monkeypatch.setattr(library_tools, "get_pool", lambda: ScriptPool(ScriptConn([("FROM documents", rows)])))
        out = await library_tools.list_library_documents.ainvoke({"name": "Acme"})
        lines = out.splitlines()
        assert lines[0] == "2 document(s) in Sangam's library for 'Acme':"
        assert "document 1 · Annual report" in lines[1] and lines[1].endswith("archived copy: read_library_document")
        assert "untitled · document · undated" in lines[2] and "link only" in lines[2]

    async def test_a_failure_is_returned_by_type(self, monkeypatch):
        monkeypatch.setattr(library_tools, "get_pool", lambda: BrokenPool())
        out = await library_tools.list_library_documents.ainvoke({"name": "Acme"})
        assert out == "list_library_documents failed: RuntimeError"


class TestReadLibrary:
    DOC = {"id": 5, "title": "Annual report", "source_url": "https://acme.org/ar.pdf", "storage_path": ARCHIVED}

    def pool(self, monkeypatch, doc):
        monkeypatch.setattr(library_tools, "get_pool", lambda: ScriptPool(ScriptConn([("FROM documents", doc)])))

    def stored(self, monkeypatch, data):
        async def download(bucket, key, max_bytes):
            assert bucket == "source-archive"
            return data
        monkeypatch.setattr(library_tools.storage, "download", download)

    async def test_a_non_pdf_has_no_archived_copy(self, monkeypatch):
        self.pool(monkeypatch, {**self.DOC, "storage_path": "source-archive/a/b.html"})
        assert "no archived copy" in await library_tools.read_library_document.ainvoke({"document_id": 5})

    async def test_a_word_file_is_read_by_paragraph(self, monkeypatch):
        from tests.test_cov_pipeline_vault_office_docs import docx_bytes

        self.pool(monkeypatch, {**self.DOC, "storage_path": "source-archive/a/call.docx"})
        self.stored(monkeypatch, docx_bytes(["Call for proposals", "Grants up to Rs 50 lakh"]))
        out = await library_tools.read_library_document.ainvoke({"document_id": 5, "start_page": 2})
        assert "say which paragraph." in out and "2 paragraphs. start_page counts paragraphs" in out
        assert out.endswith("[para 2] Grants up to Rs 50 lakh")

    async def test_a_word_range_with_nothing_in_it(self, monkeypatch):
        from tests.test_cov_pipeline_vault_office_docs import docx_bytes

        self.pool(monkeypatch, {**self.DOC, "storage_path": "source-archive/a/call.docx"})
        self.stored(monkeypatch, docx_bytes(["One"]))
        out = await library_tools.read_library_document.ainvoke({"document_id": 5, "start_page": 4})
        assert out.endswith("1 paragraphs and no text in that range.")

    async def test_a_failed_download(self, monkeypatch):
        self.pool(monkeypatch, self.DOC)
        self.stored(monkeypatch, None)
        out = await library_tools.read_library_document.ainvoke({"document_id": 5})
        assert out == "Document 5 could not be downloaded."

    async def test_pages_are_marked_and_the_source_is_named(self, monkeypatch):
        self.pool(monkeypatch, self.DOC)
        self.stored(monkeypatch, b"%PDF")
        monkeypatch.setattr(library_tools, "extract_pdf_text",
                            lambda path, s, e: ("--- page 2 ---\nCSR spend Rs 4 crore", 9))
        out = await library_tools.read_library_document.ainvoke({"document_id": 5, "start_page": 2})
        assert "## document 5 · Annual report" in out and "source_url https://acme.org/ar.pdf" in out
        assert "9 pages." in out and "[page 2]\nCSR spend Rs 4 crore" in out

    async def test_a_scanned_range_says_so(self, monkeypatch):
        self.pool(monkeypatch, self.DOC)
        self.stored(monkeypatch, b"%PDF")
        monkeypatch.setattr(library_tools, "extract_pdf_text", lambda path, s, e: ("   ", 4))
        out = await library_tools.read_library_document.ainvoke({"document_id": 5})
        assert "4 pages and no text in that range: most likely scanned." in out

    async def test_a_long_read_is_cut_on_a_line(self, monkeypatch):
        self.pool(monkeypatch, self.DOC)
        self.stored(monkeypatch, b"%PDF")
        monkeypatch.setattr(library_tools, "MAX_CHARS", 50)
        monkeypatch.setattr(library_tools, "extract_pdf_text", lambda path, s, e: ("line one\n" * 20, 3))
        out = await library_tools.read_library_document.ainvoke({"document_id": 5})
        assert "… cut at 50 characters of 3 pages" in out

    async def test_a_failure_is_returned_by_type(self, monkeypatch):
        monkeypatch.setattr(library_tools, "get_pool", lambda: BrokenPool())
        out = await library_tools.read_library_document.ainvoke({"document_id": 5})
        assert out == "read_library_document failed: RuntimeError"


ARPAN = {"id": 7, "name": "Arpan", "slug": "arpan"}


@contextmanager
def picked(sources: Sources):
    token = run_sources.CURRENT.set(sources)
    try:
        yield
    finally:
        run_sources.CURRENT.reset(token)


class TestListVault:
    def pool(self, monkeypatch, org=ARPAN, docs=()):
        pool = ScriptPool(ScriptConn([("FROM orgs", org)]))
        monkeypatch.setattr(vault_tools, "get_pool", lambda: pool)

        async def documents(p, org_id):
            return list(docs)
        monkeypatch.setattr(vault, "documents", documents)
        return pool

    async def test_a_member_lists_their_one_org_by_default(self, monkeypatch):
        pool = self.pool(monkeypatch, docs=[
            {"id": 12, "title": "Sanction letter", "doc_type": "letter", "as_of": "2026-01-01"},
            {"id": 13, "title": None, "doc_type": None, "as_of": None, "created_at": datetime(2026, 2, 3, tzinfo=UTC)},
            {"id": 14, "title": "x", "doc_type": "y", "as_of": None},
        ])
        with running_as(MEMBER):
            out = await vault_tools.list_vault_documents.ainvoke({})
        assert pool.conn.calls[0][1][0] == "7"
        assert out.splitlines() == [
            "Arpan (org_id 7): 3 file(s) in its Doc Vault.",
            "  document 12 · Sanction letter · letter · 2026-01-01",
            "  document 13 · untitled · file · 2026-02-03",
            "  document 14 · x · y · undated",
        ]

    async def test_an_org_marker_is_accepted(self, monkeypatch):
        pool = self.pool(monkeypatch)
        with running_as(MEMBER):
            out = await vault_tools.list_vault_documents.ainvoke({"org": "[org:7]"})
        assert pool.conn.calls[0][1][0] == "7" and out == "Arpan (org_id 7) has no files in its Doc Vault."

    async def test_a_steward_of_two_must_name_one(self, monkeypatch):
        self.pool(monkeypatch)
        with running_as(STEWARD):
            out = await vault_tools.list_vault_documents.ainvoke({})
        assert out.startswith("Name the organisation")

    async def test_the_picked_vault_is_the_only_one(self, monkeypatch):
        self.pool(monkeypatch, org={"id": 8, "name": "Kabil", "slug": "kabil"})
        with picked(Sources(web=False, vault_org=7, vault_docs=frozenset({12}))), running_as(STEWARD):
            out = await vault_tools.list_vault_documents.ainvoke({"org": "kabil"})
        assert out == "REFUSED: this run's Doc Vault files are org 7's; list that one."

    async def test_the_picked_vault_is_the_default(self, monkeypatch):
        pool = self.pool(monkeypatch)
        with picked(Sources(web=False, vault_org=7, vault_docs=frozenset({12}))), running_as(STEWARD):
            out = await vault_tools.list_vault_documents.ainvoke({})
        assert pool.conn.calls[0][1][0] == "7" and out.startswith("Arpan (org_id 7)")

    async def test_an_unknown_org(self, monkeypatch):
        self.pool(monkeypatch, org=None)
        with running_as(STAFF):
            out = await vault_tools.list_vault_documents.ainvoke({"org": "nobody"})
        assert out == "No Doc Vault you can read for 'nobody'."

    async def test_a_failure_is_returned_by_type(self, monkeypatch):
        monkeypatch.setattr(vault_tools, "get_pool", lambda: BrokenPool())
        with running_as(STAFF):
            out = await vault_tools.list_vault_documents.ainvoke({"org": "7"})
        assert out == "list_vault_documents failed: RuntimeError"


class TestReadVault:
    async def test_a_readable_file_is_read(self, monkeypatch):
        async def doc(pool, doc_id):
            return {"id": doc_id, "org_id": 7}

        async def read(d, **kw):
            return f"read {d['id']} {kw['sheet']!r} {kw['start_row']}"
        monkeypatch.setattr(vault, "document", doc)
        monkeypatch.setattr(vault, "read", read)
        monkeypatch.setattr(vault_tools, "get_pool", lambda: None)
        with running_as(MEMBER):
            out = await vault_tools.read_vault_document.ainvoke({"document_id": 12, "sheet": "Grants", "start_row": 4})
        assert out == "read 12 'Grants' 4"

    async def test_a_failure_names_only_its_type(self, monkeypatch):
        async def doc(pool, doc_id):
            raise ValueError("cell B7 says Rs 4 lakh")
        monkeypatch.setattr(vault, "document", doc)
        monkeypatch.setattr(vault_tools, "get_pool", lambda: None)
        with running_as(MEMBER):
            out = await vault_tools.read_vault_document.ainvoke({"document_id": 12})
        assert out == "read_vault_document failed: ValueError"


class TestSaveVault:
    async def test_a_database_failure_names_only_its_type(self, monkeypatch):
        async def in_vault(p, org_id, ids):
            raise RuntimeError("secret row")
        monkeypatch.setattr(vault, "in_vault", in_vault)
        monkeypatch.setattr(vault_tools, "get_pool", lambda: None)
        save = {"entity_name": "Acme Foundation", "entity_kind": "funder", "org_id": 7, "documents_read": [],
                "findings": []}
        with running_as(MEMBER):
            out = await vault_tools.save_vault_findings.ainvoke({"findings": save})
        assert out.startswith("save_vault_findings failed: RuntimeError.") and "secret" not in out
