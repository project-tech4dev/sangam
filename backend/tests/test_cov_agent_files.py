"""download_file and read_pdf, with a fake HTTP transport and a temp downloads folder."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from pypdf import PdfWriter

from app.agent.tools import files
from app.core.egress import EgressRefused


@pytest.fixture(autouse=True)
def tmp_downloads(monkeypatch, tmp_path):
    folder = tmp_path / "dl"
    monkeypatch.setattr(files, "get_settings", lambda: SimpleNamespace(downloads_dir=str(folder)))
    return folder


def _serve(monkeypatch, handler):
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(files, "guarded_client", client)


def test_downloads_dir_is_created(tmp_downloads):
    assert files.downloads_dir() == tmp_downloads and tmp_downloads.is_dir()


@pytest.mark.parametrize("line, expected", [
    ("A N N U A L  R E P O R T", "ANNUAL REPORT"),
    ("an ordinary line of text", "an ordinary line of text"),
])
def test_letter_spaced_lines_are_collapsed(line, expected):
    assert files._normalize_line(line) == expected


async def test_download_saves_the_file_and_hints_read_pdf(monkeypatch, tmp_downloads):
    _serve(monkeypatch, lambda req: httpx.Response(200, content=b"%PDF-data",
                                                   headers={"content-type": "application/pdf"}))
    out = await files.download_file.ainvoke({"url": "https://example.org/a/report.pdf?x=1"})
    assert "Saved to" in out and "9 bytes, application/pdf" in out and "read_pdf('report.pdf')" in out
    assert (tmp_downloads / "report.pdf").read_bytes() == b"%PDF-data"


async def test_download_name_is_made_safe(monkeypatch, tmp_downloads):
    _serve(monkeypatch, lambda req: httpx.Response(200, content=b"x"))
    out = await files.download_file.ainvoke({"url": "https://e.org/f", "filename": "../../etc/pass wd.csv"})
    assert (tmp_downloads / "pass_wd.csv").exists() and "read_pdf" not in out


async def test_download_over_the_limit_is_refused_and_removed(monkeypatch, tmp_downloads):
    monkeypatch.setattr(files, "MAX_DOWNLOAD_BYTES", 4)
    _serve(monkeypatch, lambda req: httpx.Response(200, content=b"0123456789"))
    out = await files.download_file.ainvoke({"url": "https://e.org/big.bin"})
    assert "exceeds the" in out and not (tmp_downloads / "big.bin").exists()


async def test_an_http_error_is_reported(monkeypatch):
    _serve(monkeypatch, lambda req: httpx.Response(404))
    out = await files.download_file.ainvoke({"url": "https://e.org/missing.pdf"})
    assert out.startswith("ERROR: download of https://e.org/missing.pdf failed (HTTPStatusError")


async def test_a_refused_address_returns_the_guard_reply(monkeypatch):
    def refuse(req):
        raise EgressRefused("refused: private address")

    _serve(monkeypatch, refuse)
    assert await files.download_file.ainvoke({"url": "http://10.0.0.1/x"}) == "refused: private address"


async def test_any_other_error_is_a_string(monkeypatch):
    def broken(**kwargs):
        raise ValueError("bad url")

    monkeypatch.setattr(files, "guarded_client", broken)
    assert await files.download_file.ainvoke({"url": "nope"}) == "download_file failed: ValueError: bad url"


def test_read_pdf_names_what_is_there_when_missing(tmp_downloads):
    out = files.read_pdf.invoke({"filename": "x.pdf"})
    assert "not found" in out and "(none)" in out
    (tmp_downloads / "b.pdf").write_bytes(b"")
    assert "Available files: b.pdf" in files.read_pdf.invoke({"filename": "x.pdf"})


def test_read_pdf_reports_an_unreadable_file(tmp_downloads):
    files.downloads_dir()
    (tmp_downloads / "bad.pdf").write_bytes(b"not a pdf")
    assert files.read_pdf.invoke({"filename": "bad.pdf"}).startswith("ERROR: could not read bad.pdf")


def test_read_pdf_says_a_scan_has_no_text(tmp_downloads):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    files.downloads_dir()
    with open(tmp_downloads / "scan.pdf", "wb") as fh:
        writer.write(fh)
    assert "no extractable text layer" in files.read_pdf.invoke({"filename": "scan.pdf"})


class _Page:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


def _fake_reader(monkeypatch, pages):
    monkeypatch.setattr(files, "PdfReader", lambda path: SimpleNamespace(pages=[_Page(t) for t in pages]))


def test_extract_reads_the_range_and_normalises(monkeypatch, tmp_path):
    _fake_reader(monkeypatch, ["one", None, "H E L L O  T H E R E", "four"])
    text, total = files.extract_pdf_text(tmp_path / "x.pdf", 0, 3)
    assert total == 4
    assert text == "--- page 1 ---\none\n\n--- page 3 ---\nHELLO THERE"


def test_extract_stops_early_on_a_long_document(monkeypatch, tmp_path):
    _fake_reader(monkeypatch, ["x" * (files.PDF_TEXT_CHARS * 3), "never read"])
    text, _ = files.extract_pdf_text(tmp_path / "x.pdf")
    assert "never read" not in text


def test_read_pdf_truncates_long_text(monkeypatch, tmp_downloads):
    files.downloads_dir()
    (tmp_downloads / "long.pdf").write_bytes(b"")
    _fake_reader(monkeypatch, ["y" * (files.PDF_TEXT_CHARS + 10)])
    out = files.read_pdf.invoke({"filename": "long.pdf"})
    assert out.startswith("[long.pdf: 1 pages]") and "[truncated — 1 pages total" in out


def test_read_pdf_returns_short_text_whole(monkeypatch, tmp_downloads):
    files.downloads_dir()
    (tmp_downloads / "s.pdf").write_bytes(b"")
    _fake_reader(monkeypatch, ["short"])
    assert files.read_pdf.invoke({"filename": "s.pdf"}) == "[s.pdf: 1 pages]\n\n--- page 1 ---\nshort"
