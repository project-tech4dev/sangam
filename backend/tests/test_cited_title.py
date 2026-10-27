"""cited_title: the name a URL cited with no document finding is written with."""

from __future__ import annotations

import pytest

from app.ingest.writer import cited_title


@pytest.mark.parametrize(("url", "source_name", "title"), [
    ("https://give.do/ngo/kabil", "  Give.do NGO profile - Kabil ", "Give.do NGO profile - Kabil"),
    ("https://www.ashrayahasthatrust.org/cupa", "research", "ashrayahasthatrust.org — Cupa"),
    ("https://indiacsr.in/csr-spend_2024-report.pdf", "IndiaCSR", "indiacsr.in — Csr spend 2024 report"),
    ("https://www.thehindu.com/news/cities/girls-in-stem/article68123456.ece", None,
     "thehindu.com — Girls in stem"),
    ("https://ngodarpan.gov.in/", "", "ngodarpan.gov.in"),
    ("https://example.org/a%20page", None, "example.org — A page"),
    ("not a url", None, "not a url"),
])
def test_cited_title(url, source_name, title):
    assert cited_title(url, source_name) == title
