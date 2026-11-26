"""Step 12 of the change check: today's fingerprint against the baseline's."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.ingest.reading import fetch
from app.ingest.reading.fingerprint import bytes_hash, text_hash
from app.ingest.refresh import compare, fetch_status
from app.ingest.refresh.baseline import Baseline
from app.ingest.refresh.fetch_status import DEAD, OK, UNVERIFIED, Today

URL = "https://funder.example/about"
REAL_CLIENT = fetch._client


def base(fingerprint: str, url: str = URL, kind: str = "page") -> Baseline:
    return Baseline(url, 7, kind, fingerprint, "k", 31, date(2026, 11, 14))


class TestCompare:
    def test_the_same_fingerprint_is_unchanged(self):
        [c] = compare.compare([base("a" * 64)], [Today(URL, OK, "HTTP 200", fingerprint="a" * 64)])
        assert c.status == compare.UNCHANGED

    def test_another_fingerprint_differs(self):
        [c] = compare.compare([base("a" * 64)], [Today(URL, OK, "HTTP 200", fingerprint="b" * 64)])
        assert c.status == compare.DIFFERS

    @pytest.mark.parametrize("status", [UNVERIFIED, DEAD])
    def test_a_failed_fetch_keeps_its_status(self, status):
        [c] = compare.compare([base("a" * 64)], [Today(URL, status, "HTTP 403")])
        assert c.status == status

    def test_every_baseline_needs_its_fetch(self):
        with pytest.raises(ValueError):
            compare.compare([base("a" * 64)], [])

    def test_describe(self):
        compared = compare.compare(
            [base("a" * 64), base("c" * 64, url="https://funder.example/x"), base("d" * 64, url="https://f.ex/y")],
            [Today(URL, OK, "", fingerprint="a" * 64), Today("https://funder.example/x", OK, "", fingerprint="e" * 64),
             Today("https://f.ex/y", UNVERIFIED, "HTTP 403")])
        out = compare.describe("zz", compared).splitlines()
        assert out[0] == "zz: 3 sources · 1 differs · 1 unchanged · 1 unverified"
        assert out[1] == f"  unchanged   {URL}  ({'a' * 12})"
        assert out[2].endswith(f"({'c' * 12} → {'e' * 12})") and out[3].endswith("(HTTP 403)")


class TestTodayIsHashedAsTheToolsHashedIt:
    """The whole check rests on this: a page that did not change must give the fingerprint research saved."""

    @pytest.fixture(autouse=True)
    def offline(self, monkeypatch):
        async def allowed(url):
            return None

        async def upload(bucket, key, data, content_type):
            return key
        recorded: list[str] = []

        async def remember(url, kind, fingerprint, key):
            recorded.append(fingerprint)
        monkeypatch.setattr(fetch, "check_url", allowed)
        monkeypatch.setattr(fetch.storage, "upload", upload)
        monkeypatch.setattr(fetch, "remember", remember)
        monkeypatch.setattr(fetch, "downloads_dir", lambda: self.downloads)
        return recorded

    def serve(self, monkeypatch, response):
        monkeypatch.setattr(fetch, "_client", lambda original, **kw: REAL_CLIENT(
            original, transport=httpx.MockTransport(lambda r: response), **kw))

    async def test_a_page(self, monkeypatch, offline, tmp_path):
        self.downloads = tmp_path
        self.serve(monkeypatch, httpx.Response(200, text="We fund  schools.\n", headers={"content-type": "text/plain"}))
        await fetch.read_page_text(URL)
        today = await fetch_status.fetch_today(base(offline[0]), tmp_path)
        assert today.fingerprint == offline[0] == text_hash("We fund schools.")
        assert compare.compare([base(offline[0])], [today])[0].status == compare.UNCHANGED

    async def test_a_document_without_text_by_its_bytes(self, monkeypatch, offline, tmp_path):
        self.downloads = tmp_path / "downloads"
        self.downloads.mkdir()
        (tmp_path / "scratch").mkdir()
        self.serve(monkeypatch, httpx.Response(200, content=b"%PDF-1.4 scanned", headers={"content-type": "application/pdf"}))
        url = "https://funder.example/ar.pdf"
        await fetch.fetch_document_file(url, None)
        today = await fetch_status.fetch_today(base(offline[0], url, "document"), tmp_path / "scratch")
        assert today.fingerprint == offline[0] == bytes_hash(b"%PDF-1.4 scanned")

    async def test_a_failed_fetch_has_no_fingerprint(self, monkeypatch, tmp_path):
        self.downloads = tmp_path
        self.serve(monkeypatch, httpx.Response(403))
        assert (await fetch_status.fetch_today(base("a" * 64), tmp_path)).fingerprint is None
