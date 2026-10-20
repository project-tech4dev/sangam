"""Staff workbooks: picking, scanning, rendering and figure checks, over small workbooks built in memory."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from app.ingest import staff_sources as ss
from app.integrations import storage


def xlsx(sheets: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _fresh_cache():
    ss._cache.clear()
    ss._locks.clear()
    yield
    ss._cache.clear()
    ss._locks.clear()


def doc(i=7, path="staff-sources/mca_csr/abc.xlsx", h="h1", name="mca_csr"):
    return {"id": i, "source_name": name, "source_url": ss.SOURCE_URL_PREFIX + f"id{i}",
            "storage_path": path, "content_hash": h}


class TestNaming:
    def test_dataset_id_is_base_name_hash(self):
        assert ss.dataset_id("a/b/report.xlsx") == ss.dataset_id("report.xlsx")
        assert len(ss.dataset_id("x.xlsx")) == 12

    def test_derived_names(self):
        ident = ss.dataset_id("f.xlsx")
        assert ss.object_key("mca_csr", "f.xlsx") == f"mca_csr/{ident}.xlsx"
        assert ss.source_url("f.xlsx") == ss.SOURCE_URL_PREFIX + ident
        assert ss.title("mca_csr", "f.xlsx") == f"Staff dataset · mca_csr · {ident}"

    def test_is_staff_source_url(self):
        assert ss.is_staff_source_url(ss.SOURCE_URL_PREFIX + "x")
        assert not ss.is_staff_source_url(None)
        assert not ss.is_staff_source_url("https://example.org")

    def test_picked_id_keeps_script_id_only_in_staff_bucket(self):
        assert ss.picked_id("staff-sources/mca_csr/0123456789ab.xlsx") == "0123456789ab"
        other = ss.picked_id("org-vault/0123456789ab.xlsx")
        assert other != "0123456789ab" and len(other) == 12

    @pytest.mark.parametrize("path", ["", "nobucket", "b/", "b/../x", "b/./x", "b//x", "-bad/x"])
    def test_split_any_refuses(self, path):
        assert ss.split_any(path) is None

    def test_split_any_accepts_any_bucket(self):
        assert ss.split_any("whatever/a/b.xlsx") == ("whatever", "a/b.xlsx")


class TestCheckPick:
    def test_not_a_path(self):
        assert "not a <bucket>/<file>" in ss.check_pick("x")

    def test_other_bucket(self):
        assert "only files in the" in ss.check_pick("org-vault/a.xlsx")

    def test_not_xlsx(self):
        assert "only .xlsx" in ss.check_pick("staff-sources/a.csv")

    def test_registry_folder_names_source(self):
        assert ss.check_pick("staff-sources/mca_csr/a.xlsx") == ("staff-sources", "mca_csr/a.xlsx", "mca_csr")

    def test_unknown_folder_falls_back_to_bucket(self):
        assert ss.check_pick("staff-sources/misc/a.XLSX")[2] == "staff-sources"
        assert ss.check_pick("staff-sources/a.xlsx")[2] == "staff-sources"


class TestRegister:
    async def test_refused_path_returns_reason(self):
        assert isinstance(await ss.register(None, "nope"), str)

    async def test_download_failure(self, monkeypatch):
        async def download(*a, **k):
            return None
        monkeypatch.setattr(storage, "download", download)
        assert "could not be downloaded" in await ss.register(None, "staff-sources/a.xlsx")

    async def test_unreadable_bytes_name_only_the_type(self, monkeypatch):
        async def download(*a, **k):
            return b"secret cell value"
        monkeypatch.setattr(storage, "download", download)
        out = await ss.register(None, "staff-sources/a.xlsx")
        assert "not a readable .xlsx" in out and "secret" not in out

    async def test_writes_row_and_caches_bytes(self, monkeypatch):
        data = xlsx({"S": [["a"]]})
        seen = {}

        async def download(*a, **k):
            return data

        async def upsert(pool, **kw):
            seen.update(kw)
            return 42, "inserted"
        monkeypatch.setattr(storage, "download", download)
        monkeypatch.setattr(ss.documents_repo, "upsert_source_dataset", upsert)
        assert await ss.register(None, "staff-sources/mca_csr/a.xlsx") == 42
        assert seen["source_key"] == "mca_csr"
        assert seen["storage_path"] == "staff-sources/mca_csr/a.xlsx"
        assert seen["source_url"].startswith(ss.SOURCE_URL_PREFIX)
        assert seen["extractor_version"] == ss.PICKED_VERSION
        assert ("staff-sources/mca_csr/a.xlsx", seen["content_hash"]) in ss._cache


class TestSearchTerms:
    def test_folds_and_strips_suffixes(self):
        assert ss.search_terms(["The Tata Steel Ltd.", "tata steel", None, "ab", "Foo Pvt Limited"]) == [
            "tata steel", "foo"]


class TestScanAndRender:
    def test_header_rows_and_matching_row_with_contacts_dropped(self):
        data = xlsx({"FY23": [
            ["Company", "Amount", "Email"],
            ["Name", "Rs", "contact"],
            ["note", "x", "y"],
            ["Acme Corp", 10, "a@b.com"],
            ["Other", 5, "c@d.com"],
        ], "Empty": [["Nothing", "here"]]})
        sheets = ss.scan(data, ["acme corp"])
        assert [s[0] for s in sheets] == ["FY23"]
        _, rows, drop = sheets[0]
        assert [r for r, _, _ in rows] == [1, 2, 3, 4]
        assert drop == {3}
        text = ss.render(doc(), sheets)
        assert "[source:7#FY23!A4]" in text and "a@b.com" not in text and "Other" not in text

    def test_only_sheet_filters(self):
        data = xlsx({"FY23": [["Acme"]], "FY24": [["Acme"]]})
        assert [s[0] for s in ss.scan(data, ["acme"], only_sheet="fy24")] == ["FY24"]

    def test_numbered_heading_brings_its_section(self):
        rows = [["h1", "h2"], ["h1", "h2"], ["h1", "h2"], [None, None], ["1. Acme projects"]]
        rows += [[f"p{i}", i] for i in range(5)]
        data = xlsx({"S": rows})
        _, got, _ = ss.scan(data, ["acme projects"])[0]
        nums = [r for r, _, _ in got]
        assert 5 in nums and all(r in nums for r in range(6, 11))

    def test_heading_and_row_under_it_shown_as_context(self):
        rows = [["h"], ["h"], ["h"], ["Region North"], ["Col A", "Col B"], ["Acme", 3]]
        _, got, _ = ss.scan(xlsx({"S": rows}), ["acme"])[0]
        assert [r for r, _, _ in got] == [1, 2, 3, 4, 5, 6]

    def test_side_by_side_blocks_show_only_the_matching_block(self):
        rows = [
            ["Block A", None, None, "Block B", None, None],
            ["Name", "Amt", "X", "Name", "Amt", "X"],
            ["Acme", 1, 2, "Other", 3, 4],
        ]
        sheets = ss.scan(xlsx({"S": rows}), ["acme"])
        _, got, _ = sheets[0]
        r, _, keep = got[-1]
        assert r == 3 and keep == {1, 2, 3}
        assert "Other" not in ss.render(doc(), sheets).splitlines()[-1]

    def test_block_starts_needs_sparse_top_over_dense_second(self):
        assert ss._block_starts(("a", "b"), ("x", "y", "z", "w")) == []
        assert ss._block_starts(("a",), ("x",)) == []
        assert ss._in_blocks(("x", "y"), ["acme"], [1]) is None

    def test_cell_redaction(self):
        assert ss._cell("call +91 98765 43210") == "[phone removed]"
        assert ss._cell("2019-2020-2021-2022") == "2019-2020-2021-2022"
        assert ss._cell(9876543210) == "9876543210"
        assert ss._cell("x@y.org") == "[email removed]"
        assert len(ss._cell("a" * 500)) == 300


def patch_docs(monkeypatch, datasets, data=None, variants=()):
    async def list_source_datasets(pool, ids=None):
        return [d for d in datasets if ids is None or d["id"] in ids]

    async def name_variants(pool, *, match, limit=5):
        return list(variants)

    async def download(*a, **k):
        return data(a) if callable(data) else data
    monkeypatch.setattr(ss.documents_repo, "list_source_datasets", list_source_datasets)
    monkeypatch.setattr(ss.funders_repo, "name_variants", name_variants)
    monkeypatch.setattr(storage, "download", download)


BOOK = xlsx({"FY23": [["Company", "Spent"], ["Acme Foundation", 12.5], ["Other", 1]]})


class TestReadRows:
    async def test_short_name(self, monkeypatch):
        patch_docs(monkeypatch, [])
        assert "at least three letters" in await ss.read_rows(None, "ab")

    async def test_no_datasets(self, monkeypatch):
        patch_docs(monkeypatch, [])
        assert "No staff dataset is registered" in await ss.read_rows(None, "Acme")
        assert "None of documents [3]" in await ss.read_rows(None, "Acme", documents=[3])

    async def test_match_uses_funder_aliases(self, monkeypatch):
        patch_docs(monkeypatch, [doc()], BOOK, variants=[{"name": "Acme Foundation", "aliases": ["AF Trust"]}])
        out = await ss.read_rows(None, "Acme Foundation")
        assert "1 of 1 staff datasets" in out and "af trust" in out
        assert "[source:7#FY23!A2]" in out  # three header rows always show, so no exclusion check here

    async def test_no_match_hints_parent(self, monkeypatch):
        patch_docs(monkeypatch, [doc()], BOOK)
        assert "No row matched" in await ss.read_rows(None, "Zeta Corp")

    async def test_every_file_failing(self, monkeypatch):
        patch_docs(monkeypatch, [doc(1), doc(2, path="bad")], None)
        out = await ss.read_rows(None, "Acme")
        assert "could not read 2 staff file(s)" in out
        assert "could not be downloaded" in out

    async def test_one_failure_listed_after_results(self, monkeypatch):
        def data(args):
            if args[1] == "mca_csr/boom.xlsx":
                raise RuntimeError("cell secret")
            if args[1] == "mca_csr/junk.xlsx":
                return b"junk"
            return BOOK
        patch_docs(monkeypatch, [doc(1), doc(2, path="staff-sources/mca_csr/boom.xlsx"),
                                 doc(3, path="staff-sources/mca_csr/junk.xlsx")], data)
        out = await ss.read_rows(None, "Acme Foundation")
        assert "document 2 (mca_csr) could not be read (RuntimeError)" in out
        assert "document 3 (mca_csr) could not be read (" in out
        assert "cell secret" not in out and "[source:1#FY23!A2]" in out

    async def test_long_output_cut_keeps_failure_lines(self, monkeypatch):
        rows = [["Company", "Note"]] + [[f"Acme row {i}", "x" * 250] for i in range(400)]
        big = xlsx({"S": rows})
        patch_docs(monkeypatch, [doc(1), doc(2, path="bad")], big)
        out = await ss.read_rows(None, "Acme")
        assert "output cut at" in out and out.endswith("could not be downloaded.")
        assert len(out) <= ss.MAX_CHARS + 200

    async def test_workbook_is_downloaded_once(self, monkeypatch):
        calls = []

        def data(args):
            calls.append(args)
            return BOOK
        patch_docs(monkeypatch, [doc()], data)
        await ss.read_rows(None, "Acme")
        await ss.read_rows(None, "Acme")
        assert len(calls) == 1

    def test_cache_evicts_oldest_over_budget(self, monkeypatch):
        monkeypatch.setattr(ss, "_CACHE_MAX_BYTES", 10)
        ss._remember(("a", ""), b"x" * 8)
        ss._remember(("b", ""), b"y" * 8)
        assert list(ss._cache) == [("b", "")]


class TestBrowse:
    async def test_needs_documents(self):
        assert "needs the document ids" in await ss.browse(None, [])

    async def test_unknown_documents(self, monkeypatch):
        patch_docs(monkeypatch, [])
        assert "None of documents [9]" in await ss.browse(None, [9])

    async def test_outline(self, monkeypatch):
        patch_docs(monkeypatch, [doc()], BOOK)
        out = await ss.browse(None, [7])
        assert out.startswith("Outline") and "sheet 'FY23': 3 filled rows × 2 columns" in out

    async def test_page_of_one_sheet_says_where_more_starts(self, monkeypatch):
        rows = [["Name", "Phone"], ["h2", "x"], ["h3", "x"]] + [[f"org{i}", "123"] for i in range(10)]
        patch_docs(monkeypatch, [doc()], xlsx({"Data": rows, "Other": [["z"]]}))
        out = await ss.browse(None, [7], sheet="data", start_row=4, limit=3)
        assert "Rows 4–6 of sheet 'data'" in out
        assert "org0" in out and "org3" not in out and "start_row=7" in out
        assert "B4" not in out  # the Phone column is dropped

    async def test_missing_sheet_and_failures(self, monkeypatch):
        def data(args):
            if "boom" in args[1]:
                raise ValueError("x")
            return BOOK
        patch_docs(monkeypatch, [doc(1), doc(2, path="bad"), doc(3, path="staff-sources/x/boom.xlsx")], data)
        out = await ss.browse(None, [1, 2, 3], sheet="nope")
        assert "document 1 has no sheet matching 'nope'" in out
        assert "document 2 (mca_csr) could not be downloaded" in out
        assert "document 3 (mca_csr) could not be read (ValueError)" in out

    async def test_long_output_cut(self, monkeypatch):
        rows = [["h"], ["h"], ["h"]] + [[f"row {i}", "y" * 290] for i in range(400)]
        patch_docs(monkeypatch, [doc()], xlsx({"S": rows}))
        out = await ss.browse(None, [7], sheet="S", limit=500)
        assert "output cut at" in out and len(out) <= ss.MAX_CHARS + 200


class TestHoldUnmarked:
    def test_each_reason(self):
        url = ss.SOURCE_URL_PREFIX + "aaa"
        findings = [
            {"concept": "web", "source_url": "https://x.org"},
            {"concept": "nomark", "source_url": url, "evidence": "plain"},
            {"concept": "unknown", "source_url": ss.SOURCE_URL_PREFIX + "zzz", "evidence": "[source:1#S!A1]"},
            {"concept": "other", "source_url": url, "evidence": "[source:2#S!A1]"},
            {"concept": "ok", "source_url": url, "evidence": "[source:1#S!B12]"},
        ]
        kept, held = ss.hold_unmarked(findings, {url: 1})
        assert [f["concept"] for f in kept] == ["web", "ok"]
        assert [h.split(":")[0] for h in held] == ["nomark", "unknown", "other"]


class TestFigures:
    @pytest.mark.parametrize("value,expected", [
        (True, None), (None, None), (12, (12.0, None)), ("n/a", None),
        ("1,234.5 lakhs", (1234.5, "lakh")), ("3 Cr", (3.0, "crore")), ("Rs 4cr", (4.0, "crore")),
        ("7 lacs", (7.0, "lakh")), ("9", (9.0, None)),
    ])
    def test_cell_amount(self, value, expected):
        assert ss.cell_amount(value) == expected

    def _finding(self, value, unit, ev="[source:7#S!A2]"):
        return {"concept": "spend", "source_url": doc()["source_url"], "evidence": ev,
                "amount": {"value": value, "unit": unit, "text": "x"}}

    def test_mismatches(self):
        rows = {("S", 2): ("Acme", 12.5, "3 lakh")}
        assert ss.figure_mismatches(self._finding(12.5, "crore"), 7, "mca_csr", rows) == []
        assert ss.figure_mismatches(self._finding(12.5, "lakh"), 7, "mca_csr", rows)  # sheet is in crore
        assert ss.figure_mismatches(self._finding(12.5, "lakh"), 7, "other", rows) == []
        assert ss.figure_mismatches(self._finding(3, "lakh"), 7, "mca_csr", rows) == []
        out = ss.figure_mismatches(self._finding(99, "crore", ev=""), 7, "mca_csr", rows)
        assert "no readable row" in out[0]

    async def test_hold_mismatched_reads_cited_rows(self, monkeypatch):
        d = doc()
        patch_docs(monkeypatch, [d], xlsx({"S": [["Company", "Spent"], ["Acme", 12.5], ["Other", 4]]}))
        findings = [
            {"concept": "plain", "source_url": d["source_url"]},
            {"concept": "web", "source_url": "https://x.org", "amount": {"value": 1, "unit": "crore", "text": ""}},
            self._finding(12.5, "crore"),
            self._finding(13, "crore", ev="[source:7#S!B2] [source:7#Missing!A1]"),
        ]
        kept, held = await ss.hold_mismatched(findings, {d["source_url"]: d})
        assert [f["concept"] for f in kept] == ["plain", "web", "spend"]
        assert len(held) == 1 and "S!row 2" in held[0]

    async def test_hold_mismatched_when_workbook_unreadable(self, monkeypatch):
        d = doc()
        patch_docs(monkeypatch, [d], b"junk")
        kept, held = await ss.hold_mismatched([self._finding(1, "crore")], {d["source_url"]: d})
        assert kept == [] and "could not be re-opened" in held[0]

    async def test_hold_mismatched_when_download_fails(self, monkeypatch):
        d = doc()
        patch_docs(monkeypatch, [d], None)
        _, held = await ss.hold_mismatched([self._finding(1, "crore")], {d["source_url"]: d})
        assert "could not be re-opened" in held[0]
