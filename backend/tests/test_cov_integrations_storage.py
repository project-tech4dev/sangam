"""Storage client calls against httpx.MockTransport: every failure is a return value, never a raise."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.integrations import storage

ON = Settings(supabase_url="https://x.supabase.co/", supabase_service_key="svc")
OFF = Settings(supabase_url="", supabase_service_key="")


@pytest.fixture
def serve(monkeypatch):
    """Route Storage calls to a handler; returns the list of requests seen."""
    seen: list[httpx.Request] = []

    def install(handler):
        def wrapped(request):
            seen.append(request)
            return handler(request)

        monkeypatch.setattr(storage, "get_settings", lambda: ON)
        monkeypatch.setattr(storage, "_client", lambda: httpx.AsyncClient(
            base_url="https://x.supabase.co/storage/v1", transport=httpx.MockTransport(wrapped)))
        return seen

    return install


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setattr(storage, "get_settings", lambda: OFF)


def test_client_carries_the_service_key(monkeypatch):
    monkeypatch.setattr(storage, "get_settings", lambda: ON)
    client = storage._client()
    assert str(client.base_url) == "https://x.supabase.co/storage/v1/"
    assert client.headers["apikey"] == "svc" and client.headers["Authorization"] == "Bearer svc"


def test_disabled_logs_once(monkeypatch, off, caplog):
    monkeypatch.setattr(storage, "_warned", False)
    with caplog.at_level("INFO"):
        assert storage._disabled() and storage._disabled()
    assert sum("Storage disabled" in r.message for r in caplog.records) == 1


def test_qualify_and_split_round_trip():
    assert storage.split(storage.qualify(storage.ORG_VAULT, "4/a.pdf")) == (storage.ORG_VAULT, "4/a.pdf")
    assert storage.split("org-vault/4/../5/x") is None
    assert storage.split("other/x") is None


async def test_every_call_is_a_no_op_when_off(off):
    assert await storage.move("b", "a", "c") is False
    assert await storage.list_buckets() == []
    assert await storage.list_all("b") == []
    assert await storage.signed_url("b", "k") is None
    assert await storage.signed_upload_url("b", "k") is None
    assert await storage.download("b", "k") is None
    assert await storage.read("b", "k") is None
    assert await storage.brief_link("kabil") is None


async def test_move_posts_the_keys(serve):
    seen = serve(lambda r: httpx.Response(200, json={}))
    assert await storage.move("org-vault", "a/1", "b/1") is True
    assert json.loads(seen[0].content) == {"bucketId": "org-vault", "sourceKey": "a/1", "destinationKey": "b/1"}


async def test_a_failed_move_is_false(serve):
    serve(lambda r: httpx.Response(500))
    assert await storage.move("b", "a", "c") is False


@pytest.mark.parametrize("status, body, duplicate", [
    (200, b"{}", False),
    (409, b"not json", True),
    (400, b"not json", False),
    (400, json.dumps({"statusCode": "409"}).encode(), True),
    (400, json.dumps({"error": "Duplicate"}).encode(), True),
    (400, json.dumps({"code": "KeyAlreadyExists"}).encode(), True),
    (400, json.dumps({"error": "Other"}).encode(), False),
])
def test_is_duplicate(status, body, duplicate):
    assert storage._is_duplicate(httpx.Response(status, content=body)) is duplicate


async def test_upload_too_large_is_refused_without_a_request(serve):
    seen = serve(lambda r: httpx.Response(200))
    assert await storage.upload("b", "k", b"12345", "text/plain", max_bytes=4) is None and seen == []


async def test_upload_sets_upsert_and_returns_the_key(serve):
    seen = serve(lambda r: httpx.Response(200, json={}))
    assert await storage.upload("b", "k/x", b"d", "", replace=True) == "k/x"
    assert seen[0].headers["x-upsert"] == "true"
    assert seen[0].headers["content-type"] == "application/octet-stream"


async def test_a_duplicate_upload_counts_as_stored(serve):
    serve(lambda r: httpx.Response(400, json={"error": "Duplicate"}))
    assert await storage.upload("b", "k", b"d", "text/plain") == "k"


async def test_a_rejected_upload_is_none(serve):
    serve(lambda r: httpx.Response(500))
    assert await storage.upload("b", "k", b"d", "text/plain") is None


async def test_list_prefix_ignores_a_non_list_and_errors(serve):
    serve(lambda r: httpx.Response(200, json={"oops": 1}))
    assert await storage.list_prefix("b", "p") == []
    serve(lambda r: httpx.Response(200, content=b"not json"))
    assert await storage.list_prefix("b", "p") == []


async def test_list_buckets(serve):
    serve(lambda r: httpx.Response(200, json=[{"id": "org-vault"}]))
    assert await storage.list_buckets() == [{"id": "org-vault"}]
    serve(lambda r: httpx.Response(200, json={"x": 1}))
    assert await storage.list_buckets() == []
    serve(lambda r: httpx.Response(503))
    assert await storage.list_buckets() == []


async def test_list_all_walks_folders_and_pages(serve, monkeypatch):
    monkeypatch.setattr(storage, "LIST_PAGE", 2)

    def handler(request):
        body = json.loads(request.content)
        prefix, offset = body["prefix"], body["offset"]
        if prefix == "4" and offset == 0:
            return httpx.Response(200, json=[{"name": "b.pdf", "id": "1", "metadata": {"size": 9},
                                              "updated_at": "t"},
                                             {"name": "sub", "id": None}])
        if prefix == "4" and offset == 2:
            return httpx.Response(200, json=[{"name": ".emptyFolderPlaceholder", "id": "2"}])
        if prefix == "4/sub":
            return httpx.Response(200, json=[{"name": "a.pdf", "id": "3"}])
        return httpx.Response(200, json={"not": "a list"})

    serve(handler)
    assert await storage.list_all("org-vault", "/4/") == [
        {"key": "4/b.pdf", "size": 9, "updated_at": "t"},
        {"key": "4/sub/a.pdf", "size": None, "updated_at": None},
    ]


async def test_list_all_stops_on_a_non_list_page(serve):
    serve(lambda r: httpx.Response(200, json={"error": "x"}))
    assert await storage.list_all("b") == []


async def test_list_all_is_empty_on_a_bad_entry(serve):
    serve(lambda r: httpx.Response(200, json=[{"id": "1"}]))  # no name: KeyError
    assert await storage.list_all("b") == []


async def test_archived_key_is_the_newest(serve):
    serve(lambda r: httpx.Response(200, json=[{"name": "abc-report.pdf"}]))
    url = "https://f.org/r.pdf"
    assert await storage.archived_key("b", url) == f"{storage.url_prefix(url)}/abc-report.pdf"
    serve(lambda r: httpx.Response(200, json=[{"id": 1}]))
    assert await storage.archived_key("b", url) is None
    serve(lambda r: httpx.Response(200, json=[]))
    assert await storage.archived_key("b", url) is None


async def test_signed_url(serve):
    serve(lambda r: httpx.Response(200, json={"signedURL": "/object/sign/b/k?token=t"}))
    assert await storage.signed_url("b", "k") == "https://x.supabase.co/storage/v1/object/sign/b/k?token=t"
    serve(lambda r: httpx.Response(200, json={}))
    assert await storage.signed_url("b", "k") is None
    serve(lambda r: httpx.Response(403))
    assert await storage.signed_url("b", "k") is None


async def test_signed_upload_url(serve):
    seen = serve(lambda r: httpx.Response(200, json={"url": "/object/upload/sign/b/k?token=t"}))
    assert (await storage.signed_upload_url("b", "k")).endswith("/storage/v1/object/upload/sign/b/k?token=t")
    assert seen[0].url.path == "/storage/v1/object/upload/sign/b/k"
    serve(lambda r: httpx.Response(200, json={"url": ""}))
    assert await storage.signed_upload_url("b", "k") is None
    serve(lambda r: httpx.Response(200, content=b"not json"))
    assert await storage.signed_upload_url("b", "k") is None


def test_vault_key_starts_with_the_org():
    key = storage.vault_key(7, "../My Report.pdf")
    assert key.startswith("7/") and key.endswith("-My_Report.pdf")


async def test_download(serve):
    serve(lambda r: httpx.Response(200, content=b"bytes"))
    assert await storage.download("b", "k") == b"bytes"
    assert await storage.download("b", "k", max_bytes=2) is None
    serve(lambda r: httpx.Response(404))
    assert await storage.download("b", "k") is None


async def test_read_tells_missing_from_failed(serve):
    serve(lambda r: httpx.Response(200, content=b"rec"))
    assert await storage.read("b", "k") == b"rec"
    serve(lambda r: httpx.Response(404))
    assert await storage.read("b", "k") is None
    serve(lambda r: httpx.Response(400, text='{"error":"not_found"}'))
    assert await storage.read("b", "k") is None
    serve(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await storage.read("b", "k")


async def test_stat_finds_the_object_by_name(serve):
    seen = serve(lambda r: httpx.Response(200, json=[{"name": "other"}, {"name": "x.pdf", "id": "9"}]))
    assert await storage.stat("b", "4/x.pdf") == {"name": "x.pdf", "id": "9"}
    assert json.loads(seen[0].content)["prefix"] == "4"
    assert await storage.stat("b", "4/missing.pdf") is None


async def test_brief_link(serve):
    def published(request):
        if request.url.path.startswith("/storage/v1/object/list/"):
            return httpx.Response(200, json=[{"name": "kabil.md"}])
        return httpx.Response(200, json={"signedURL": "/object/sign/x?t=1"})

    serve(published)
    assert (await storage.brief_link("kabil")).endswith("/storage/v1/object/sign/x?t=1")

    serve(lambda r: httpx.Response(200, json=[]))
    assert await storage.brief_link("kabil") is None

    def unsignable(request):
        if request.url.path.startswith("/storage/v1/object/list/"):
            return httpx.Response(200, json=[{"name": "kabil.md"}])
        return httpx.Response(500)

    serve(unsignable)
    with pytest.raises(storage.BriefUnreachable):
        await storage.brief_link("kabil")
