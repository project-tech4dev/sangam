"""The PDF reader in core/extract.py, with a fake pypdf reader."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import extract


@pytest.mark.parametrize("line, expected", [
    ("A N N U A L  R E P O R T", "ANNUAL REPORT"),
    ("an ordinary line of text", "an ordinary line of text"),
])
def test_letter_spaced_lines_are_collapsed(line, expected):
    assert extract._normalize_line(line) == expected


class _Page:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


def _fake_reader(monkeypatch, pages):
    monkeypatch.setattr(extract, "PdfReader", lambda path: SimpleNamespace(pages=[_Page(t) for t in pages]))


def test_extract_reads_the_range_and_normalises(monkeypatch, tmp_path):
    _fake_reader(monkeypatch, ["one", None, "H E L L O  T H E R E", "four"])
    text, total = extract.extract_pdf_text(tmp_path / "x.pdf", 0, 3)
    assert total == 4
    assert text == "--- page 1 ---\none\n\n--- page 3 ---\nHELLO THERE"


def test_extract_stops_early_on_a_long_document(monkeypatch, tmp_path):
    _fake_reader(monkeypatch, ["x" * (extract.PDF_TEXT_CHARS * 3), "never read"])
    text, _ = extract.extract_pdf_text(tmp_path / "x.pdf")
    assert "never read" not in text
