"""Doc Vault reading and checks, Word/Excel text extraction, and the docs/ renderer, with no database."""

from __future__ import annotations

import contextlib
import io
import zipfile
from types import SimpleNamespace

import pytest
from docx import Document
from openpyxl import Workbook

from app.ingest import office, render_docs, vault
from app.integrations import storage


def docx_bytes(paras, table=None):
    d = Document()
    for p in paras:
        d.add_paragraph(p)
    if table:
        t = d.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, v in enumerate(row):
                t.cell(r, c).text = v
        t.cell(0, 0).merge(t.cell(0, 1))
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def xlsx_bytes(rows, title="Sheet"):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_PML = "http://schemas.openxmlformats.org/presentationml/2006/main"
_DML = "http://schemas.openxmlformats.org/drawingml/2006/main"
_ODR = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def pptx_bytes(slides):
    """A minimal deck: slide N is stored as slide{N}.xml but listed last-first, so order comes from presentation.xml.
    A slide is a list of lines, or of rows (a list of lists) for a table."""
    def body(items):
        out = []
        for item in items:
            if isinstance(item, list):
                rows = "".join("<a:tr>" + "".join(f"<a:tc><a:txBody><a:p><a:r><a:t>{c}</a:t></a:r></a:p></a:txBody></a:tc>"
                                                  for c in row) + "</a:tr>" for row in item)
                out.append(f"<p:graphicFrame><a:graphic><a:graphicData><a:tbl>{rows}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>")
            else:
                out.append(f"<p:sp><p:txBody><a:p><a:r><a:t>{item}</a:t></a:r></a:p></p:txBody></p:sp>")
        return f'<p:sld xmlns:p="{_PML}" xmlns:a="{_DML}"><p:cSld><p:spTree>{"".join(out)}</p:spTree></p:cSld></p:sld>'

    order = list(range(len(slides), 0, -1))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ppt/presentation.xml", f'<p:presentation xmlns:p="{_PML}" xmlns:r="{_ODR}"><p:sldIdLst>'
                   + "".join(f'<p:sldId id="{255 + i}" r:id="rId{n}"/>' for i, n in enumerate(order, 1))
                   + "</p:sldIdLst></p:presentation>")
        z.writestr("ppt/_rels/presentation.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{n}" Target="slides/slide{n}.xml"/>' for n in order)
                   + "</Relationships>")
        for pos, n in enumerate(order):
            z.writestr(f"ppt/slides/slide{n}.xml", body(slides[pos]))
    return buf.getvalue()


class TestOffice:
    def test_docx_paragraphs_and_tables_in_order(self):
        data = docx_bytes(["Intro", "  ", "After"], table=[["A", "B", "C"], ["", "", ""], ["1", "2", "3"]])
        assert office.docx_paragraphs(data) == ["Intro", "After", "A\nB | C", "1 | 2 | 3"]  # a merged cell once

    def test_pptx_slides_in_presentation_order_with_table_rows(self):
        data = pptx_bytes([["Our work", "Udalguri"], [], [[["District", "SHGs"], ["Baksa", "27"]]]])
        assert office.pptx_slides(data) == ["Our work\nUdalguri", "", "District | SHGs\nBaksa | 27"]

    def test_docx_range_numbers_paragraphs_like_pages(self):
        data = docx_bytes(["Intro", "Budget", "After"], table=[["Item", "Cost", "x"], ["Books", "500", "y"]])
        assert office.docx_range(data, 2, 4) == ("[para 2] Budget\n[para 3] After\n[para 4] Item\nCost | x", 5)
        assert office.docx_range(data, 9) == ("", 5)

    def test_xlsx_markdown_caps_rows(self, monkeypatch):
        monkeypatch.setattr(office, "SHEET_ROWS", 2)
        data = xlsx_bytes([["a", None], [None, None], ["b", 2], ["c", 3]], title="Grants")
        assert office.xlsx_markdown(data) == "## Grants\na | \n… first 2 rows only"


DOC = {"id": 12, "org_id": 3, "title": "Annual report", "doc_type": "annual_report", "storage_path": "org-vault/3/ar.pdf"}


class TestTextLines:
    def test_a_long_line_is_split_at_a_space(self):
        lines = office.text_lines(("word " * 1000).encode())
        assert len(lines) == 3 and all(len(line) <= office.LINE_MAX for line in lines)

    def test_a_line_with_no_space_is_split_hard(self):
        assert [len(line) for line in office.text_lines(b"x" * 4500)] == [2000, 2000, 500]

    def test_a_range_numbers_lines_and_skips_blank_ones(self):
        text, total = office.text_range(b"one\n\nthree\nfour", 2, 3)
        assert (text, total) == ("[line 3] three", 4)

    def test_bad_bytes_do_not_raise(self):
        assert office.text_range(b"caf\xe9", 1)[0] == "[line 1] caf\ufffd"


class TestVaultUrls:
    def test_url_round_trip(self):
        assert vault.document_id(vault.url(12)) == 12
        assert vault.document_id(vault.url(12) + "/") == 12
        assert vault.document_id(vault.URL_PREFIX + "abc") is None
        assert vault.document_id("https://example.org/12") is None
        assert vault.marked_ids("see [vault:3#p2] and [vault:4#para1]") == {3, 4}


class FakeConn:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    async def execute(self, sql, params=None):
        self.sql.append((sql, params))
        rows = self.rows

        class C:
            async def fetchall(self):
                return rows

            async def fetchone(self):
                return rows[0] if rows else None
        return C()


class FakePool:
    def __init__(self, rows):
        self.conn = FakeConn(rows)

    @contextlib.asynccontextmanager
    async def connection(self):
        yield self.conn


class TestVaultQueries:
    async def test_queries_are_scoped_to_the_vault_bucket(self):
        pool = FakePool([{"id": 1}, {"id": 2}])
        assert await vault.documents(pool, 3) == [{"id": 1}, {"id": 2}]
        assert await vault.document(pool, 1) == {"id": 1}
        assert await vault.in_vault(pool, 3, {2, 1}) == {1, 2}
        assert await vault.in_vault(pool, 3, set()) == set()
        assert all(p[-1] == "org-vault/%" for _, p in pool.conn.sql)
        assert pool.conn.sql[2][1][0] == [1, 2]

    async def test_document_rows(self):
        conn = FakeConn([{"id": 5}])
        out = await vault.document_rows(conn, [{"source_url": vault.url(5)}, {"source_url": "https://x.org"}])
        assert out == {vault.url(5): 5} and conn.sql[0][1][0] == [5]
        assert await vault.document_rows(conn, [{"source_url": "https://x.org"}]) == {}


class TestVaultRead:
    @pytest.fixture
    def download(self, monkeypatch):
        box = {}

        async def dl(bucket, key, max_bytes):
            return box.get("data")
        monkeypatch.setattr(storage, "download", dl)
        return box

    async def test_refusals(self, download):
        assert "no file on record" in await vault.read({**DOC, "storage_path": None})
        assert "is not a PDF, Word" in await vault.read({**DOC, "storage_path": "org-vault/3/x.ppt"})
        assert "could not be downloaded" in await vault.read(DOC)

    async def test_a_row_naming_another_orgs_file_is_not_read(self, download):
        download["data"] = b"secret"
        assert "no file on record" in await vault.read({**DOC, "storage_path": "org-vault/4/ar.pdf"})
        assert "no file on record" in await vault.read({**DOC, "storage_path": "org-vault/33/ar.pdf"})
        assert "no file on record" in await vault.read({**DOC, "org_id": None})
        assert "no file on record" in await vault.read({**DOC, "storage_path": "source-archive/3/ar.pdf"})

    async def test_pdf_pages_are_marked_and_cut(self, download, monkeypatch):
        download["data"] = b"%PDF"
        body = "--- page 1 ---\n" + ("line of text\n" * 3000) + "--- page 2 ---\nend"
        monkeypatch.setattr(vault, "extract_pdf_text", lambda path, s, e: (body, 2))
        out = await vault.read(DOC)
        assert "[vault:12#p1]" in out and "2 pages. Cite a fact" in out
        assert out.endswith("Call again with a later start_page.") and len(out) < vault.MAX_CHARS + 500

    async def test_a_text_file_is_read_by_line_and_cut_where_it_says(self, download):
        download["data"] = ("Households: 1,240\n\n" + "a long line of the dossier\n" * 2000).encode()
        out = await vault.read({**DOC, "storage_path": "org-vault/3/notes.md"})
        assert "2002 lines (start_page counts lines" in out and "[vault:12#line1] Households: 1,240" in out
        assert "#line2]" not in out and len(out) < vault.MAX_CHARS + 500
        cut = out.splitlines()[-1]
        assert cut.startswith("… cut at line ") and cut.endswith(f"start_page={int(cut.split()[4]) + 1}.")

    async def test_a_csv_is_read_by_line_and_a_later_window_names_its_columns(self, download):
        download["data"] = b"district,households\nPune,1240\nNashik,980\n"
        first = await vault.read({**DOC, "storage_path": "org-vault/3/survey.CSV"})
        assert "[vault:12#line2] Pune,1240" in first and "Columns" not in first
        later = await vault.read({**DOC, "storage_path": "org-vault/3/survey.csv"}, start_page=3)
        assert "Columns (line 1): district,households" in later and "[vault:12#line3] Nashik,980" in later
        assert "#line2]" not in later

    @pytest.mark.parametrize("name,mime", [("cert.png", "image/png"), ("cert.JPG", "image/jpeg"),
                                           ("cert.jpeg", "image/jpeg"), ("cert.webp", "image/webp")])
    async def test_an_image_comes_back_as_itself_with_its_marker(self, download, name, mime):
        download["data"] = b"\x89PNG\r\n\x1a\n"
        out = await vault.read({**DOC, "storage_path": f"org-vault/3/{name}"})
        assert out[0]["type"] == "text" and "[vault:12#image]" in out[0]["text"]
        assert out[1] == {"type": "image", "base64": "iVBORw0KGgo=", "mime_type": mime}

    async def test_an_image_too_large_for_the_model_is_refused_in_words(self, download):
        download["data"] = b"\0" * (vault.IMAGE_MAX_BYTES + 1)
        out = await vault.read({**DOC, "storage_path": "org-vault/3/scan.png"})
        assert isinstance(out, str) and "too large to read" in out

    async def test_a_scanned_pdf_says_so(self, download, monkeypatch):
        download["data"] = b"%PDF"
        monkeypatch.setattr(vault, "extract_pdf_text", lambda path, s, e: ("  ", 7))
        assert "7 pages and no text in that range: most likely scanned" in await vault.read(DOC)

    async def test_docx_paragraphs_are_paged(self, download, monkeypatch):
        download["data"] = docx_bytes([f"Para {i} " + "x" * 500 for i in range(80)])
        out = await vault.read({**DOC, "storage_path": "org-vault/3/plan.DOCX"}, start_page=3)
        assert out.splitlines()[3] == "" and "[vault:12#para3] Para 2" in out
        assert "… cut at paragraph" in out and "Call again with start_page=" in out

    async def test_pptx_slides_are_cited_and_paged(self, download):
        download["data"] = pptx_bytes([["Intro"], ["Reach", "1,240 households"], ["Plans"]])
        out = await vault.read({**DOC, "storage_path": "org-vault/3/deck.PPTX"}, start_page=2)
        assert "3 slides (start_page counts slides" in out
        assert "[vault:12#slide2] Reach\n1,240 households" in out and "[vault:12#slide3] Plans" in out
        assert "#slide1]" not in out

    async def test_xlsx_rows_are_cited_and_contacts_dropped(self, download):
        download["data"] = xlsx_bytes([["Grant", "Email"], ["h2", "x"], ["h3", "y"], ["Acme 5 lakh", "a@b.org"]])
        out = await vault.read({**DOC, "storage_path": "org-vault/3/g.xlsx"}, sheet="Sheet", limit=999)
        assert "[vault:12#Sheet!A4] A4='Acme 5 lakh'" in out and "a@b.org" not in out

    def test_xlsx_text_is_cut(self):
        data = xlsx_bytes([["h"], ["h"], ["h"]] + [[f"row {i} " + "z" * 250] for i in range(200)])
        out = vault.xlsx_text(DOC, data, "Sheet", 1, 200)
        assert out.endswith("Read one sheet.")


VURL = vault.url(4)


class TestVaultChecks:
    def test_check_findings(self):
        findings = [
            {"concept": "a", "source_url": "https://x.org"},
            {"concept": "b", "source_url": vault.url(9), "evidence": "[vault:9#p1]"},
            {"concept": "c", "source_url": VURL, "evidence": "no marker"},
            {"concept": "d", "source_url": VURL, "evidence": "[vault:4#p2]"},
        ]
        problems = vault.check_findings(findings, {4})
        assert [p.split(":")[0] for p in problems] == ["a", "b", "c"]

    def test_hold_at_promote(self):
        findings = [
            {"concept": "identity", "source_url": "https://x.org"},
            {"concept": "identity", "source_url": VURL, "evidence": "nothing"},
            {"concept": "contact", "source_url": VURL, "evidence": "[vault:4#p1]"},
            {"concept": "rfp", "source_url": VURL, "evidence": "[vault:4#p1]"},
        ]
        kept, held = vault.hold_at_promote(findings, "funder")
        assert kept == [findings[0], findings[3]]
        assert held == ["identity from document 4: no [vault:4#…] marker",
                        "contact from document 4: the organisation's own fact, kept private"]
        _, held_org = vault.hold_at_promote(findings[3:], "org")
        assert held_org == ["rfp from document 4: an organisation's own documents stay with it"]


class TestRenderDocs:
    def test_replace_block(self):
        text = "intro\n<!-- generated:x -->\nold\n<!-- /generated -->\noutro"
        assert render_docs.replace_block(text, "x", "new\n") == \
            "intro\n<!-- generated:x -->\nnew\n<!-- /generated -->\noutro"
        assert render_docs.replace_block("intro\n", "y", "b").endswith("<!-- generated:y -->\nb\n<!-- /generated -->\n")

    def test_client_block(self):
        assert "No organisation" in render_docs.client_block([])
        out = render_docs.client_block([{"canonical_name": None, "entity_name": "acme", "researched_on": "d",
                                         "status": "ok", "fact_count": 3, "slug": "acme"}])
        assert "| acme | d | ok | 3 | [entity file](../../entities/acme.md) |" in out

    async def test_main_needs_database_url(self, monkeypatch, capsys):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert await render_docs.main() == 1
        assert "DATABASE_URL is not set" in capsys.readouterr().err

    async def test_main_writes_entities_and_client_blocks(self, monkeypatch, tmp_path, capsys):
        rows = [
            {"slug": "acme", "entity_kind": "funder", "status": "complete", "canonical_name": "Acme",
             "entity_name": "acme", "researched_on": "2026-01-01", "fact_count": 2},
            {"slug": "acme", "entity_kind": "funder", "status": "complete", "canonical_name": "Acme",
             "entity_name": "acme", "researched_on": "2026-02-01", "fact_count": 5},
            {"slug": "zeta", "entity_kind": "unknown", "status": "wrong_entity", "canonical_name": None,
             "entity_name": "zeta", "researched_on": "2026-01-01", "fact_count": 0},
        ]

        class Conn:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def execute(self, sql, params=None):
                data = rows if "entity_research" in sql else [{"slug": "ngo-one", "name": "NGO One"}]

                class C:
                    async def fetchall(self):
                        return data
                return C()

        async def connect(url, row_factory):
            return Conn()
        built = []

        async def build(history):
            built.append(len(history))
            return f"# {history[-1]['slug']}\n"

        async def publish(slug, md):
            return slug if slug == "acme" else None
        clients = tmp_path / "clients"
        (clients / "ngo-one").mkdir(parents=True)
        (clients / "ngo-one" / "README.md").write_text("Hand written.\n")
        (clients / "draft").mkdir()
        (clients / "README.md").write_text("Index\n")
        monkeypatch.setenv("DATABASE_URL", "postgresql://x")
        monkeypatch.setattr(render_docs, "psycopg", SimpleNamespace(AsyncConnection=SimpleNamespace(connect=connect)))
        monkeypatch.setattr(render_docs, "build", build)
        monkeypatch.setattr(render_docs, "publish_markdown", publish)
        monkeypatch.setattr(render_docs, "ENTITIES", tmp_path / "entities")
        monkeypatch.setattr(render_docs, "CLIENTS", clients)

        assert await render_docs.main() == 0
        assert built == [2, 1]
        assert (tmp_path / "entities" / "acme.md").read_text() == "# acme\n"
        readme = (clients / "ngo-one" / "README.md").read_text()
        assert readme.startswith("Hand written.") and "| Acme | 2026-02-01 | complete | 5 |" in readme
        assert "zeta" not in readme
        assert "[NGO One](ngo-one/README.md) | 1 funders researched" in (clients / "README.md").read_text()
        out = capsys.readouterr().out
        assert "docs/entities: 2 file(s), 1 published" in out and "zeta (unknown/wrong_entity)" in out
        assert "refreshed 1 client file(s)" in out
