"""read_page hands back a page's real links, and a 404 its home page's, so the researcher stops guessing paths."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from app.ingest.reading import fetch, snapshots
from app.ingest.reading.links import MAX_LABEL, MAX_LINKS, link_list, same_site_links
from app.ingest.tools import research_tools

HOME = "https://www.iocl.com/"
NAV = ('<html><body><nav>'
       '<a href="/pages/contact">Contact</a>'
       '<a href="/pages/csr-overview">CSR</a>'
       '<a href="https://www.iocl.com/pages/csr-overview#top">CSR again</a>'
       '<a href="https://cdn.iocl.com/reports/AR-2024.pdf">Annual Report 2024</a>'
       '<a href="https://twitter.com/iocl">Twitter</a>'
       '<a href="mailto:csr@iocl.com">Mail</a>'
       '<a href="javascript:void(0)">Menu</a>'
       '<a href="/">Home</a>'
       '</nav><article><h1>Indian Oil</h1>'
       + "<p>Indian Oil spent Rs 400 crore on CSR in FY2024-25 across health and education.</p>" * 5
       + "</article></body></html>")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    async def allowed(url):
        return None

    async def upload(bucket, key, data, content_type):
        return key

    fetch._TIMEOUTS.clear()
    monkeypatch.setattr(fetch, "check_url", allowed)
    monkeypatch.setattr(fetch.storage, "upload", upload)


def serve(monkeypatch, handler):
    real = fetch._client
    monkeypatch.setattr(fetch, "_client",
                        lambda original, **kw: real(original, transport=httpx.MockTransport(handler), **kw))


class TestSameSiteLinks:
    def test_keeps_the_site_and_its_subdomains_once_each_wanted_first(self):
        links = same_site_links(NAV, HOME)
        assert links == [
            ("Annual Report 2024", "https://cdn.iocl.com/reports/AR-2024.pdf"),
            ("CSR", "https://www.iocl.com/pages/csr-overview"),
            ("Contact", "https://www.iocl.com/pages/contact"),
        ]

    def test_is_capped(self):
        html = "".join(f'<a href="/p{i}">Page {i}</a>' for i in range(MAX_LINKS + 20))
        assert len(same_site_links(html, HOME)) == MAX_LINKS

    def test_an_icon_link_is_named_by_its_label(self):
        html = ('<a href="/csr" title="CSR Policy"><i class="icon"></i></a>'
                '<a href="/ar"><img src="ar.png" alt="Annual Report"></a>')
        assert same_site_links(html, HOME) == [("CSR Policy", "https://www.iocl.com/csr"),
                                               ("Annual Report", "https://www.iocl.com/ar")]

    def test_a_long_label_is_cut_and_a_pdf_says_how_to_open_it(self):
        out = link_list([("x" * 300, "https://www.iocl.com/csr"), ("Report", "https://www.iocl.com/AR.PDF")], "Links:")
        first, second = out.splitlines()[1:]
        assert len(first.split(": ", 1)[0]) == len("- ") + MAX_LABEL and first.split(": ", 1)[0].endswith("…")
        assert second == "- Report: https://www.iocl.com/AR.PDF (PDF: use fetch_document)"

    def test_a_page_with_no_links(self):
        assert same_site_links("<p>nothing</p>", HOME) == []


class TestReadPage:
    async def test_a_page_comes_back_with_its_links_before_the_text(self, monkeypatch):
        serve(monkeypatch, lambda r: httpx.Response(200, html=NAV))
        out = await research_tools.read_page.ainvoke({"url": HOME})
        assert "- CSR: https://www.iocl.com/pages/csr-overview" in out
        assert out.index("Links on this page") < out.index("Rs 400 crore")
        assert "twitter.com" not in out

    async def test_a_404_lists_the_home_page_links(self, monkeypatch):
        def handler(r):
            return httpx.Response(200, html=NAV) if r.url.path == "/" else httpx.Response(404)
        serve(monkeypatch, handler)
        out = await research_tools.read_page.ainvoke({"url": "https://www.iocl.com/pages/csr"})
        assert out.startswith("ERROR: https://www.iocl.com/pages/csr returned HTTP 404. Nothing was read.")
        assert "rather than guessing another path" in out
        assert "- CSR: https://www.iocl.com/pages/csr-overview" in out

    async def test_a_404_on_a_site_whose_home_page_fails_says_only_that(self, monkeypatch):
        serve(monkeypatch, lambda r: httpx.Response(404))
        out = await research_tools.read_page.ainvoke({"url": "https://www.iocl.com/pages/csr"})
        assert out == "ERROR: https://www.iocl.com/pages/csr returned HTTP 404. Nothing was read."

    async def test_a_missing_home_page_is_not_fetched_twice(self, monkeypatch):
        calls = []

        def handler(r):
            calls.append(str(r.url))
            return httpx.Response(404)
        serve(monkeypatch, handler)
        await research_tools.read_page.ainvoke({"url": HOME})
        assert calls == [HOME]

    async def test_a_403_is_unchanged(self, monkeypatch):
        serve(monkeypatch, lambda r: httpx.Response(403))
        assert await research_tools.read_page.ainvoke({"url": HOME}) == f"ERROR: {HOME} returned HTTP 403. Nothing was read."

    async def test_a_page_already_read_still_gives_its_links(self, monkeypatch):
        seen = snapshots.SavedReading(archive_key="aa/home.md", researched_on=date(2026, 11, 26))

        async def saved(url, fingerprint, subject):
            return seen

        async def remember(*_):
            return None
        monkeypatch.setattr(fetch, "saved_reading", saved)
        monkeypatch.setattr(fetch, "remember", remember)
        serve(monkeypatch, lambda r: httpx.Response(200, html=NAV))
        out = await fetch.read_page_text(HOME, "indian-oil")
        assert out.startswith("ALREADY READ") and "Rs 400 crore" not in out
        assert "- CSR: https://www.iocl.com/pages/csr-overview" in out

    async def test_a_path_scoped_source_lists_only_its_allowed_paths(self, monkeypatch):
        scoped = SimpleNamespace(path_scoped=True, key="give_do", name="Give.do")
        monkeypatch.setattr(fetch, "rule_for_url", lambda url: (None, scoped) if "/discover/" in url else None)
        html = ('<a href="/discover/water-trust">Water Trust</a><a href="/login">Log in</a>'
                + "<p>Give.do lists Water Trust among its verified NGOs working on rural water access.</p>" * 5)
        serve(monkeypatch, lambda r: httpx.Response(200, html=html))
        out = await research_tools.read_page.ainvoke({"url": "https://give.do/discover/a"})
        assert "https://give.do/discover/water-trust" in out and "/login" not in out
