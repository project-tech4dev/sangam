"""The same-site links a page carries, so the researcher follows a real URL instead of guessing a path."""

from __future__ import annotations

import logging
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

MAX_LINKS = 30
HEADING = "Links on this page (same site, most relevant first; open these rather than guessing a path):"
MAX_LABEL = 80  # a whole card wrapped in one <a> would otherwise send its blurb on every later turn
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
            self.found.append((self._href, " ".join("".join(self._text).split()) or " ".join(self._label.split())))
            self._href = None


def _site(host: str) -> str:
    return host.lower().removeprefix("www.")


def _same_site(link: str, page: str) -> bool:
    """The page's site or a subdomain of it (a report is often on cdn.); never a parent, which may be gov.in."""
    return link == page or link.endswith("." + page)


def same_site_links(html: str, page_url: str, limit: int | None = MAX_LINKS) -> list[tuple[str, str]]:
    """(text, url) for each distinct same-site link, the ones a funder researcher wants first."""
    parser = _Anchors()
    try:
        parser.feed(html)
    except Exception as exc:  # noqa: BLE001 - links never cost the page; keep the ones found so far
        logger.debug("link extraction stopped on %s: %s", page_url, exc)
    here = urlsplit(page_url)
    seen: dict[str, tuple[str, str]] = {}
    for href, text in parser.found:
        try:
            parts = urlsplit(urljoin(page_url, href.strip()))
            host = parts.hostname
        except ValueError:  # one malformed href ('http://[oops') must not cost the page
            continue
        if parts.scheme not in ("http", "https") or not host:
            continue
        if not _same_site(_site(host), _site(here.hostname or "")):
            continue
        url = urlunsplit(parts._replace(fragment=""))
        key = url.rstrip("/")  # /csr and /csr/ are one link
        if key == urlunsplit(here._replace(fragment="")).rstrip("/"):
            continue
        if key not in seen or (text and not seen[key][0]):
            seen[key] = (text, url)
    ranked = sorted(seen.values(), key=lambda item: -sum(w in f"{item[0]} {item[1]}".lower() for w in WANTED))
    return ranked[:limit]


def link_list(links: list[tuple[str, str]], heading: str) -> str:
    if not links:
        return ""
    return f"{heading}\n" + "\n".join(f"- {_label(text)}: {url}{_pdf(url)}" for text, url in links)


def without_links(reply: str) -> str:
    """A read_page reply without its link list, so a quote check sees only the page's own text."""
    start = reply.find(HEADING)
    if start < 0:
        return reply
    end = reply.find("\n\n", start)
    return reply[:start] + ("" if end < 0 else reply[end + 2:])


def _label(text: str) -> str:
    if not text:
        return "(no text)"
    return text if len(text) <= MAX_LABEL else text[:MAX_LABEL - 1].rstrip() + "…"


def _pdf(url: str) -> str:
    return " (PDF: use fetch_document)" if urlsplit(url).path.lower().endswith(".pdf") else ""
