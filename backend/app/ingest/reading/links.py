"""The same-site links a page carries, so the researcher follows a real URL instead of guessing a path."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

MAX_LINKS = 30
# What a funder researcher looks for first; a link naming more of these ranks higher.
WANTED = ("csr", "social", "responsib", "annual", "report", "investor", "policy", "sustainab", "brsr",
          "foundation", "governance", "grant", "impact", "about", ".pdf")


class _Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []
        self._label = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if tag == "a":
            self._href, self._text = found.get("href"), []
            self._label = found.get("aria-label") or found.get("title") or ""
        elif tag == "img" and self._href is not None:
            self._label = self._label or found.get("alt") or ""

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            # An icon or image link has no text; its label says where it goes.
            self.found.append((self._href, " ".join("".join(self._text).split()) or self._label.strip()))
            self._href = None


def _site(host: str) -> str:
    return host.lower().removeprefix("www.")


def _same_site(a: str, b: str) -> bool:
    """example.org, www.example.org and cdn.example.org are one site; a report is often on a subdomain."""
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def same_site_links(html: str, page_url: str, limit: int = MAX_LINKS) -> list[tuple[str, str]]:
    """(text, url) for each distinct same-site link, the ones a funder researcher wants first."""
    parser = _Anchors()
    parser.feed(html)
    here = urlsplit(page_url)
    seen: dict[str, str] = {}
    for href, text in parser.found:
        parts = urlsplit(urljoin(page_url, href.strip()))
        if parts.scheme not in ("http", "https") or not parts.hostname:
            continue
        if not _same_site(_site(parts.hostname), _site(here.hostname or "")):
            continue
        url = urlunsplit(parts._replace(fragment=""))
        if url.rstrip("/") == urlunsplit(here._replace(fragment="")).rstrip("/"):
            continue
        if url not in seen or (text and not seen[url]):
            seen[url] = text
    ranked = sorted(seen.items(), key=lambda item: -sum(w in f"{item[1]} {item[0]}".lower() for w in WANTED))
    return [(text, url) for url, text in ranked[:limit]]


def link_list(links: list[tuple[str, str]], heading: str) -> str:
    if not links:
        return ""
    return f"{heading}\n" + "\n".join(f"- {text or '(no text)'}: {url}" for text, url in links)
