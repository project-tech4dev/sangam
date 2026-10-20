"""reading_tools: the brief, the funder's archived PDFs, the chosen form and read_files, each refusing without a proposal."""

import json
from contextlib import asynccontextmanager
from uuid import UUID

import pytest

from app.core.security import CallerScope
from app.ingest import vault
from app.integrations import storage
from app.proposals import context
from app.proposals.tools import reading_tools as rt


class FakePool:
    """Answers each SQL by the first handler whose substring it contains; records every query."""

    def __init__(self, handlers):
        self.handlers, self.seen = handlers, []

    @asynccontextmanager
    async def connection(self):
        yield self

    async def execute(self, sql, params=()):
        self.seen.append((sql, params))
        rows = next((r for key, r in self.handlers if key in sql), [])
        return _Cursor(rows)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None

    async def fetchall(self):
        return self.rows


def proposal(work=None, can_edit=True):
    return context.Current(id=1, title="t", org_id=7, org_name="SeSTA", funder_id=3, funder_name="ABF",
                           work=work or {"stage": 2}, scope=CallerScope(UUID(int=5), False, {7: "admin"}),
                           can_edit=can_edit)


@pytest.fixture
def opened(monkeypatch):
    def _open(p, handlers=()):
        pool = FakePool(list(handlers))

        async def current():
            return p

        monkeypatch.setattr(context, "current", current)
        monkeypatch.setattr(rt, "get_pool", lambda: pool)
        return pool

    return _open


@pytest.fixture
def closed(monkeypatch):
    async def none():
        return None

    monkeypatch.setattr(context, "current", none)


@pytest.mark.parametrize("tool, args", [
    (rt.read_brief, {}), (rt.list_funder_documents, {}), (rt.read_funder_document, {"document_id": 1}),
    (rt.read_template, {}), (rt.read_files, {}),
])
async def test_every_tool_says_when_no_proposal_is_open(closed, tool, args):
    assert await tool.ainvoke(args) == rt.NO_PROPOSAL


@pytest.mark.parametrize("tool, args", [
    (rt.read_brief, {}), (rt.list_funder_documents, {}), (rt.read_funder_document, {"document_id": 1}),
    (rt.read_template, {}), (rt.read_files, {}),
])
async def test_a_failure_is_returned_with_its_type_not_raised(monkeypatch, tool, args):
    async def boom():
        raise RuntimeError("secret detail")

    monkeypatch.setattr(context, "current", boom)
    out = await tool.ainvoke(args)
    assert out == f"{tool.name} failed: RuntimeError"


def _brief(*facts):
    return "\n".join(f"<!-- fact {json.dumps(f)} -->" for f in facts).encode()


FACT = {"label": "CSR spend", "value": "₹12 crore", "concept": "csr_spend", "fiscal_year": "2024-25",
        "source_name": "Annual report", "source_url": "https://abf.org/ar.pdf", "evidence": "spent  ₹12 crore\n on CSR"}


class TestReadBrief:
    async def test_a_side_other_than_funder_or_org_is_refused(self, opened):
        opened(proposal())
        assert await rt.read_brief.ainvoke({"side": "board"}) == 'side is "funder" or "org".'

    async def test_the_slug_comes_from_research_first(self, opened, monkeypatch):
        pool = opened(proposal(), [("entity_research", [{"slug": "abf-research"}])])
        asked = []

        async def read(bucket, key):
            asked.append((bucket, key))
            return _brief(FACT)

        monkeypatch.setattr(storage, "read", read)
        out = await rt.read_brief.ainvoke({"side": "funder"})
        assert asked == [(storage.SOURCE_ARCHIVE, storage.brief_key("abf-research"))]
        assert "resolved_funder_id" in pool.seen[0][0] and pool.seen[0][1] == (3,)
        assert "Sangam's research brief for ABF: 1 fact(s)." in out
        assert "- csr_spend: CSR spend · ₹12 crore · 2024-25 · Annual report https://abf.org/ar.pdf" in out
        assert 'quote: "spent ₹12 crore on CSR"' in out

    async def test_the_org_side_falls_back_to_the_catalog_slug(self, opened, monkeypatch):
        pool = opened(proposal(), [("FROM orgs", [{"slug": "sesta"}])])

        async def read(bucket, key):
            return None

        monkeypatch.setattr(storage, "read", read)
        out = await rt.read_brief.ainvoke({"side": "org"})
        assert out.startswith("Sangam holds no research brief for SeSTA.")
        assert "resolved_org_id" in pool.seen[0][0] and pool.seen[1][1] == (7,)

    async def test_no_slug_at_all_means_no_brief(self, opened, monkeypatch):
        opened(proposal())

        async def never(bucket, key):
            raise AssertionError("no slug, no read")

        monkeypatch.setattr(storage, "read", never)
        assert (await rt.read_brief.ainvoke({})).startswith("Sangam holds no research brief for ABF")

    async def test_private_and_unlinked_facts_never_leave_the_proposal(self, opened, monkeypatch):
        opened(proposal(), [("entity_research", [{"slug": "abf"}])])
        private = {**FACT, "source_url": "https://files.sangam.invalid/x"}
        unlinked = {**FACT, "source_url": "vault:4"}

        async def read(bucket, key):
            return _brief(private, unlinked)

        monkeypatch.setattr(storage, "read", read)
        assert await rt.read_brief.ainvoke({}) == "Sangam's brief for ABF holds no public facts."

    async def test_a_long_brief_is_cut_and_says_so(self, opened, monkeypatch):
        opened(proposal(), [("entity_research", [{"slug": "abf"}])])

        async def read(bucket, key):
            return _brief(*[{**FACT, "fiscal_year": None, "as_of": None}] * (rt.BRIEF_FACTS + 3))

        monkeypatch.setattr(storage, "read", read)
        out = await rt.read_brief.ainvoke({})
        assert out.endswith("… 3 more not shown.")
        assert out.count("\n- ") == rt.BRIEF_FACTS


class TestFunderDocuments:
    async def test_none_archived(self, opened):
        opened(proposal())
        assert await rt.list_funder_documents.ainvoke({}) == "Sangam has archived no documents for ABF."

    async def test_each_document_is_listed_with_its_id(self, opened):
        pool = opened(proposal(), [("FROM documents", [
            {"id": 9, "title": "Annual report", "doc_type": "annual_report", "as_of": "2024-25"},
            {"id": 8, "title": None, "doc_type": None, "as_of": None}])])
        out = await rt.list_funder_documents.ainvoke({})
        assert out.splitlines() == ["2 document(s) Sangam archived for ABF:",
                                    "  document 9 · Annual report · annual_report · 2024-25",
                                    "  document 8 · untitled · document · undated"]
        assert pool.seen[0][1] == (3, f"{storage.SOURCE_ARCHIVE}/%")

    async def test_a_document_not_the_funders_is_refused(self, opened):
        pool = opened(proposal())
        out = await rt.read_funder_document.ainvoke({"document_id": 12})
        assert out == "Document 12 is not one of ABF's archived documents."
        assert pool.seen[0][1] == (12, f"{storage.SOURCE_ARCHIVE}/%", 3)

    async def test_a_non_pdf_is_not_read(self, opened):
        opened(proposal(), [("FROM documents", [{"id": 12, "title": "x", "source_url": "u",
                                                 "storage_path": f"{storage.SOURCE_ARCHIVE}/a/b.html"}])])
        assert "is not one of ABF's" in await rt.read_funder_document.ainvoke({"document_id": 12})

    async def test_a_pdf_that_will_not_download_says_so(self, opened, monkeypatch):
        opened(proposal(), [("FROM documents", [{"id": 12, "title": "x", "source_url": "u",
                                                 "storage_path": f"{storage.SOURCE_ARCHIVE}/a/b.PDF"}])])

        async def download(bucket, key, max_bytes):
            return None

        monkeypatch.setattr(storage, "download", download)
        assert await rt.read_funder_document.ainvoke({"document_id": 12}) == "Document 12 could not be downloaded."

    async def test_a_pdf_is_read_by_page_range(self, opened, monkeypatch):
        opened(proposal(), [("FROM documents", [{"id": 12, "title": "x", "source_url": "u",
                                                 "storage_path": f"{storage.SOURCE_ARCHIVE}/a/b.pdf"}])])
        seen = {}

        async def download(bucket, key, max_bytes):
            seen["where"] = (bucket, key)
            return b"%PDF"

        def pdf(doc, data, start, end):
            seen["pages"] = (doc["id"], data, start, end)
            return "page text"

        monkeypatch.setattr(storage, "download", download)
        monkeypatch.setattr(rt, "_pdf", pdf)
        out = await rt.read_funder_document.ainvoke({"document_id": 12, "start_page": 3, "end_page": 4})
        assert out == "page text"
        assert seen == {"where": (storage.SOURCE_ARCHIVE, "a/b.pdf"), "pages": (12, b"%PDF", 3, 4)}


class TestReadTemplate:
    async def test_no_form_chosen(self, opened):
        opened(proposal({"stage": 2}))
        assert (await rt.read_template.ainvoke({})).startswith("No funder form was chosen")

    async def test_the_orgs_own_upload_is_read_from_the_vault(self, opened, monkeypatch):
        opened(proposal({"template": {"document_id": 41}}))

        async def document(pool, doc_id):
            return {"id": doc_id, "org_id": 7, "storage_path": "org-vault/7/form.docx"}

        async def read(doc, start_page, end_page):
            return f"vault {doc['id']} {start_page}-{end_page}"

        monkeypatch.setattr(vault, "document", document)
        monkeypatch.setattr(vault, "read", read)
        assert await rt.read_template.ainvoke({"start_page": 2}) == "vault 41 2-None"

    async def test_another_orgs_file_falls_back_to_the_public_archive(self, opened, monkeypatch):
        pool = opened(proposal({"template": {"document_id": 41}}))

        async def document(pool, doc_id):
            return {"id": doc_id, "org_id": 99, "storage_path": "org-vault/99/form.docx"}

        monkeypatch.setattr(vault, "document", document)
        assert await rt.read_template.ainvoke({}) == "The funder's form has no copy Sangam can read."
        assert pool.seen[0][1] == (41, f"{storage.SOURCE_ARCHIVE}/%")


class TestReadFiles:
    async def test_a_reader_is_refused(self, opened):
        opened(proposal(can_edit=False))
        assert (await rt.read_files.ainvoke({})).startswith("REFUSED: you can read this proposal")

    async def test_not_before_step_two(self, opened):
        opened(proposal({"stage": 1}))
        assert (await rt.read_files.ainvoke({})).startswith("REFUSED: read_files is used from step 2")

    async def test_it_hands_the_proposal_to_the_readers(self, opened, monkeypatch):
        from app.proposals import readers

        p = proposal({"stage": 2})
        opened(p)

        async def read(got, public):
            return f"read {got.id} public={public}"

        monkeypatch.setattr(readers, "read", read)
        assert await rt.read_files.ainvoke({"public": True}) == "read 1 public=True"
