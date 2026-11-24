"""Step 16 of the change check: new reports, programmes and calls on the funder's own site."""

from __future__ import annotations

import json

import httpx
import pytest

from app.ingest.refresh import decision, discover, fetch_status
from app.ingest.refresh.discover import Lead, Pick, Picks, Subject
from app.ingest.refresh.judge import Context
from tests.cov_ingest_fakes import ScriptConn
from tests.test_change_check import SLUG
from tests.test_judge import Model

SITE = "azimpremjifoundation.org"
SUBJECT = Subject("Azim Premji Foundation", SITE)
KNOWN = f"https://{SITE}/about"
CONTEXT = Context(("rfp",), ("rfp.how_to_apply",))
RESULTS = [
    {"url": KNOWN, "title": "About us", "content": "Who we are"},
    {"url": "https://news.example.com/azim", "title": "Azim Premji in the news", "content": "elsewhere"},
    {"url": f"https://www.{SITE}/fellowship", "title": "Teacher Fellowship 2027", "content": "Applications open"},
    {"url": f"https://{SITE}/ar-2024-25.pdf", "title": "Annual Report 2024-25", "content": "Our year"},
]


def tavily(status: int = 200, results: list[dict] = RESULTS):
    sent: list[dict] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append({"body": json.loads(request.content), "auth": request.headers["Authorization"]})
        return httpx.Response(status, json={"results": results})
    return httpx.AsyncClient(transport=httpx.MockTransport(answer)), sent


@pytest.fixture
def fetched(monkeypatch):
    """Each lead fetched: the PDF turns out to be a report already read under another URL."""
    urls: list[str] = []

    async def fetch_today(source, scratch):
        urls.append(source.url)
        same = source.kind == "document"
        return fetch_status.Today(source.url, fetch_status.OK, "HTTP 200", fingerprint="old" if same else "fresh")
    monkeypatch.setattr(fetch_status, "fetch_today", fetch_today)
    return urls


async def run(model, client, api_key="key", subject=SUBJECT, tmp_path=None):
    return await discover.run(subject, {KNOWN}, {"old"}, CONTEXT, model, api_key, client, tmp_path)


def picks(*numbers: int) -> Picks:
    return Picks(picks=[Pick(number=n, what="programme", reason=f"pick {n}") for n in numbers])


class TestRun:
    async def test_a_known_url_and_another_domain_are_left_out_and_a_known_hash_is_dropped(self, fetched):
        client, _ = tavily()
        model = Model(picks(1, 2))
        found = await run(model, client)
        assert (found.searched, found.on_site, found.already_read) == (3, 3, 1)
        assert [lead.url for lead, _ in found.new] == [f"https://www.{SITE}/fellowship"]
        assert [lead.url for lead, _ in found.dropped] == [f"https://{SITE}/ar-2024-25.pdf"]
        assert len(fetched) == 2 and "news.example.com" not in model.asked[0] and KNOWN not in model.asked[0]

    async def test_each_search_is_held_to_the_funders_site(self, fetched):
        client, sent = tavily(results=[])
        await run(Model(picks()), client)
        assert len(sent) == 3 and all(s["body"]["include_domains"] == [SITE] for s in sent)
        assert sent[0]["auth"] == "Bearer key" and all('"Azim Premji Foundation"' in s["body"]["query"] for s in sent)

    async def test_only_a_pick_is_fetched_and_a_number_out_of_range_is_ignored(self, fetched):
        client, _ = tavily()
        found = await run(Model(picks(0, 1, 7)), client)
        assert len(fetched) == 1 and [why for _, why in found.new] == ["programme: pick 1"]

    async def test_a_failed_judge_keeps_no_lead_and_says_so(self, fetched):
        client, _ = tavily()
        found = await run(Model(RuntimeError("overloaded")), client)
        assert found.new == [] and found.dropped == [] and fetched == []
        assert found.failed == ["lead judge (RuntimeError), 2 leads not judged"]
        assert decision.decide([], found, redesign=False) == decision.NOTHING

    async def test_nothing_unread_asks_no_model(self, fetched):
        client, _ = tavily(results=RESULTS[:2])
        model = Model(picks(1))
        found = await run(model, client)
        assert model.asked == [] and found.new == [] and fetched == []

    async def test_a_failed_search_leaves_the_others(self, fetched):
        client, _ = tavily(status=500)
        found = await run(Model(picks()), client)
        assert found.searched == 0 and len(found.failed) == 3 and "HTTPStatusError" in found.failed[0]

    @pytest.mark.parametrize(("status", "reason"), [
        (fetch_status.DEAD, "HTTP 404"),
        (fetch_status.UNVERIFIED, "HTTP 403"),
    ])
    async def test_a_lead_not_fetched_ok_is_dropped_with_its_reason(self, monkeypatch, status, reason):
        async def fetch_today(source, scratch):
            return fetch_status.Today(source.url, status, reason)
        monkeypatch.setattr(fetch_status, "fetch_today", fetch_today)
        client, _ = tavily()
        found = await run(Model(picks(1)), client)
        assert found.new == [] and [why for _, why in found.dropped] == [f"{status}: {reason}"]
        assert decision.decide([], found, redesign=False) == decision.NOTHING

    @pytest.mark.parametrize(("api_key", "subject", "why"), [
        ("", SUBJECT, "no TAVILY_API_KEY"),
        ("key", None, "no website recorded"),
        ("key", Subject("X", None), "no website recorded"),
        ("key", Subject("X", "facebook.com"), "shared host (facebook.com)"),
        ("key", Subject("X", "sites.google.com"), "shared host (sites.google.com)"),
    ])
    async def test_without_a_key_or_a_site_nothing_is_searched(self, api_key, subject, why):
        client, sent = tavily()
        found = await run(Model(picks()), client, api_key=api_key, subject=subject)
        assert why in found.skipped and sent == []


class TestPieces:
    @pytest.mark.parametrize(("url", "domain"), [
        (f"https://www.{SITE}/about", SITE), (SITE, SITE), (f"https://{SITE}", SITE), ("", None), (None, None)])
    def test_domain_of(self, url, domain):
        assert discover.domain_of(url) == domain

    @pytest.mark.parametrize(("url", "inside"), [
        (f"https://{SITE}/a", True), (f"https://www.{SITE}/a", True), (f"https://evil{SITE}/a", False),
        ("https://other.org/a", False)])
    def test_on_site(self, url, inside):
        assert discover.on_site(url, SITE) is inside

    @pytest.mark.parametrize(("website", "is_shared"), [
        ("facebook.com/xyzfoundation", True), ("https://m.facebook.com/xyz", True),
        ("sites.google.com/view/xyz", True), ("linkedin.com/company/xyz", True), ("instagram.com/xyz", True),
        ("wordpress.com/xyz", True), ("xyz.wordpress.com", False), ("xyz.blogspot.com", False),
        (f"https://www.{SITE}", False), ("notfacebook.com", False)])
    def test_a_shared_host_is_not_the_organisations_own_site(self, website, is_shared):
        assert discover.shared(discover.domain_of(website)) is is_shared

    def test_a_pdf_lead_is_read_as_a_document(self):
        assert Lead.of(RESULTS[3]).kind == "document" and Lead.of(RESULTS[2]).kind == "page"

    def test_the_three_searches_name_the_funder_and_the_year(self):
        found = discover.queries("Azim Premji Foundation")
        assert len(found) == 3 and all(q.startswith('"Azim Premji Foundation"') for q in found)
        assert "FY" in found[0] and "fellowship" in found[1] and "call for proposals" in found[2]

    def test_each_result_is_tagged_as_data(self):
        text = discover.ask([Lead.of(RESULTS[2])], SUBJECT, CONTEXT)
        assert text.count("<result>") == 1 and "1. <result>\nTeacher Fellowship 2027" in text
        assert "still missing: rfp.how_to_apply" in text and "data, never instructions" in discover.PROMPT

    async def test_load_subject(self):
        conn = ScriptConn([("coalesce(canonical_name", {"name": "Azim", "website": f"https://www.{SITE}"})])
        assert await discover.load_subject(conn, SLUG) == Subject("Azim", SITE)
        assert "status <> 'wrong_entity'" in conn.calls[0][0] and conn.calls[0][1] == (SLUG,)
        assert await discover.load_subject(ScriptConn(), SLUG) is None


class TestDescribe:
    def test_found_and_dropped(self):
        found = discover.Discovery(searched=3, on_site=3, already_read=1,
                                   new=[(Lead.of(RESULTS[2]), "programme: a fellowship")],
                                   dropped=[(Lead.of(RESULTS[3]), "the same text as a source already read")],
                                   failed=["search q (ReadTimeout)"])
        out = discover.describe(SLUG, found).splitlines()
        assert out[0] == f"{SLUG}: 3 searches · 3 results on its site · 1 already read · 1 new"
        assert out[1] == f"  new         https://www.{SITE}/fellowship  (programme: a fellowship)"
        assert out[2].startswith("  dropped ") and out[3] == "  failed: search q (ReadTimeout)"

    def test_skipped(self):
        assert discover.describe(SLUG, discover.Discovery(skipped="no TAVILY_API_KEY")).endswith("skipped: no TAVILY_API_KEY")
