"""The egress guard refuses private, loopback and metadata hosts, literal or after DNS, with no real network."""

from __future__ import annotations

import socket

import httpx
import pytest

from app.core import egress


@pytest.fixture
def dns(monkeypatch):
    """A fake resolver: host -> addresses, or OSError for an unknown host."""
    table: dict[str, list[str]] = {}

    async def resolve(host, port):
        if host not in table:
            raise socket.gaierror("no such host")
        return table[host]

    monkeypatch.setattr(egress, "_resolve", resolve)
    return table


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://2130706433/", "http://0x7f.1/", "http://127.1/",
    "http://10.0.0.5/", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://[64:ff9b::a00:1]/", "http://[2002:7f00:1::]/",
    "http://224.0.0.1/",
])
async def test_a_literal_private_address_is_refused(url, dns):
    why = await egress.private_address_refusal(url)
    assert why and "private or internal" in why


async def test_a_literal_public_address_passes(dns):
    assert await egress.private_address_refusal("https://8.8.8.8/x") is None
    assert await egress.private_address_refusal("http://[64:ff9b::808:808]/") is None


@pytest.mark.parametrize("url, words", [
    ("ftp://example.org/", "not an http(s) URL"),
    ("http://localhost:8000/", "names this machine"),
    ("http://api.localhost/", "names this machine"),
    ("http://intranet/", "single-label host"),
])
async def test_a_url_that_is_never_read(url, words, dns):
    assert words in await egress.private_address_refusal(url)


async def test_a_host_that_resolves_to_a_private_address_is_refused(dns):
    dns["evil.example.org"] = ["93.184.216.34", "10.1.2.3"]
    why = await egress.private_address_refusal("https://evil.example.org/a")
    assert "resolves to a private or internal address (10.1.2.3)" in why


async def test_a_host_that_resolves_to_public_addresses_passes(dns):
    dns["example.org"] = ["93.184.216.34"]
    assert await egress.private_address_refusal("http://example.org/") is None


async def test_a_host_that_does_not_resolve_is_refused(dns):
    assert "does not resolve" in await egress.private_address_refusal("https://nowhere.example.org/")


async def test_an_unparseable_url_is_refused_not_raised(dns):
    # httpx itself rejects a 4-digit octal octet, so the guard refuses rather than raise.
    why = await egress.private_address_refusal("http://0177.0.0.1/")
    assert "could not be checked" in why


def test_a_non_numeric_host_is_not_a_literal_ip():
    assert egress._literal_ip("example.org") is None
    assert egress._literal_ip("1.2.3.4.5") is None


async def test_resolve_strips_the_ipv6_zone(monkeypatch):
    class Loop:
        async def getaddrinfo(self, host, port, type):
            return [(0, 0, 0, "", ("fe80::1%eth0", port, 0, 0)), (0, 0, 0, "", ("1.2.3.4", port))]

    monkeypatch.setattr(egress.asyncio, "get_running_loop", lambda: Loop())
    assert await egress._resolve("x.org", 80) == ["fe80::1", "1.2.3.4"]


async def test_the_guarded_client_refuses_before_sending(dns):
    async with egress.guarded_client() as client:
        with pytest.raises(egress.EgressRefused) as refused:
            await client.get("http://169.254.169.254/latest/meta-data/")
    assert refused.value.reply.startswith("REFUSED: ")


async def test_the_guarded_client_refuses_a_redirect_to_a_private_host(dns):
    dns["public.example.org"] = ["93.184.216.34"]
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    client = egress.guarded_client(transport=httpx.MockTransport(handler))
    async with client:
        with pytest.raises(egress.EgressRefused):
            await client.get("http://public.example.org/start")
    assert sent == ["http://public.example.org/start"]


async def test_the_guarded_client_lets_a_public_host_through(dns):
    dns["public.example.org"] = ["93.184.216.34"]
    client = egress.guarded_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="ok")))
    async with client:
        assert (await client.get("https://public.example.org/")).text == "ok"
