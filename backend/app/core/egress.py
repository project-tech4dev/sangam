"""Outbound fetches never reach a private, loopback, link-local or internal address, before or after DNS.
Shared by Import's research tools and the news pipeline; checked on every redirect hop."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from typing import Any

import httpx

_NUMERIC_HOST = re.compile(r"[0-9a-fA-Fx.]+")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The address a host names literally, including inet_aton forms (2130706433, 0x7f.1, 0177.0.0.1, 127.1)."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if _NUMERIC_HOST.fullmatch(host):
        try:
            return ipaddress.IPv4Address(socket.inet_aton(host))
        except OSError:
            return None
    return None


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip in _NAT64:  # NAT64 reaches the IPv4 address in its last 32 bits
            return _is_public(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        for inner in (ip.ipv4_mapped, ip.sixtofour, ip.teredo[1] if ip.teredo else None):
            if inner is not None and not _is_public(inner):
                return False
    return ip.is_global and not ip.is_multicast


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]).split("%", 1)[0] for info in infos]


async def private_address_refusal(url: str) -> str | None:
    """None when the URL's host is a public address before and after DNS, else why it is refused. Never raises."""
    try:
        parsed = httpx.URL(url)
        host = parsed.raw_host.decode("ascii").lower().rstrip(".")
        if parsed.scheme not in ("http", "https") or not host:
            return f"{url} is not an http(s) URL with a host."
        if host == "localhost" or host.endswith(".localhost"):
            return f"{url} names this machine, which is never read."
        ip = _literal_ip(host)
        if ip is not None:
            return None if _is_public(ip) else f"{url} names a private or internal address, which is never read."
        if "." not in host:
            return f"{url} names a single-label host, which is internal and never read."
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = await _resolve(host, port)
        except OSError:
            return f"{host} does not resolve, so it is not read."
        for address in addresses:
            if not _is_public(ipaddress.ip_address(address)):
                return f"{host} resolves to a private or internal address ({address}), which is never read."
        return None
    except Exception as exc:  # noqa: BLE001 - a check that cannot decide refuses
        return f"{url} could not be checked ({type(exc).__name__}), so it is not read."


class EgressRefused(Exception):
    """Raised from a request hook: a hop goes to an address this process must not reach."""

    def __init__(self, reply: str):
        super().__init__(reply)
        self.reply = reply


def guarded_client(**kwargs: Any) -> httpx.AsyncClient:
    """An httpx client whose every request, redirects included, passes private_address_refusal first."""

    async def guard(request: httpx.Request) -> None:
        why = await private_address_refusal(str(request.url))
        if why:
            raise EgressRefused(f"REFUSED: {why}")

    return httpx.AsyncClient(follow_redirects=True, event_hooks={"request": [guard]}, **kwargs)
