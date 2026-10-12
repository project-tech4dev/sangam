"""The sources Sangam may read, and the rule that governs each one.

The inventory lives in data/sources/*.json so it can be reviewed as a diff by
someone who does not write Python. Loading it is the only thing this module
does: an access rule is a security decision, so it changes in a pull request,
never at runtime. `_self_check()` runs at import and raises, which is what
buys back the "no parse step at boot" property the SQL catalog has by being
Python (docs/SQL_AGENT.md).
"""

from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from importlib.resources import files
from types import MappingProxyType
from urllib.parse import parse_qsl, unquote, urlsplit

import httpx

_DATA = files("app.ingest") / "data" / "sources"
_FILES = ("funders.json", "ngos.json", "rfps.json", "media.json")


class AccessRule(StrEnum):
    """The legend from the source inventory. The first three are dispatchable; the last two are path-scoped."""

    OPEN_API = "open_api"
    CRAWL_ALLOWED = "crawl_allowed"
    LICENSED_API = "licensed_api"
    """A paid API Sangam holds a key for; its terms, not robots.txt, govern use."""
    CRAWL_PER_SITE = "crawl_allowed_check_each_site"
    CRAWL_WITH_PERMISSION = "crawl_only_with_permission"
    NO_SCRAPING = "no_scraping_manual_entry_allowed"
    MANUAL_ONLY = "manual_entry_only_automation_blocked"
    LICENCE_NEEDED = "licence_or_paid_access_needed"
    PARTNER_PERMISSION = "partner_permission_internal"
    REFERENCE_ONLY = "reference_only"
    NOT_CHECKED = "not_checked"
    MANUAL_AGGREGATOR = "manual_aggregator"
    INTERNAL_RESEARCH = "internal_research"


class Category(StrEnum):
    FUNDER = "funder"
    NGO = "ngo"
    RFP = "rfp"
    MEDIA = "media"


# A crawler may run only for these. Everything else is reported as refused, with
# its basis, so an unsupported source is a row in the summary and not a silence.
DISPATCHABLE: frozenset[AccessRule] = frozenset(
    {AccessRule.OPEN_API, AccessRule.CRAWL_ALLOWED, AccessRule.LICENSED_API}
)

# Read by the researcher's fetch tools on the paths an entry names and nowhere else; never dispatched.
PATH_SCOPED: frozenset[AccessRule] = frozenset({AccessRule.MANUAL_AGGREGATOR, AccessRule.INTERNAL_RESEARCH})
# Never read on a path-scoped source, whatever its allowlist says. Fixed in code, matched per segment.
_SIGN_IN_SEGMENTS = frozenset({"login", "log-in", "logout", "signin", "sign-in", "signup", "sign-up", "auth",
                               "oauth", "sso", "account", "accounts", "admin", "dashboard"})

# Ordered permissive → restrictive. When several products share a host the
# strictest wins, so a permissive product can never unlock a restricted one.
_STRICTNESS: tuple[AccessRule, ...] = (
    AccessRule.OPEN_API,
    AccessRule.CRAWL_ALLOWED,
    AccessRule.LICENSED_API,
    # On a host shared with a refusing rule, the refusal governs every path the scoped entry does not claim.
    AccessRule.INTERNAL_RESEARCH,
    AccessRule.MANUAL_AGGREGATOR,
    AccessRule.CRAWL_PER_SITE,
    AccessRule.CRAWL_WITH_PERMISSION,
    AccessRule.NOT_CHECKED,
    AccessRule.REFERENCE_ONLY,
    AccessRule.LICENCE_NEEDED,
    AccessRule.PARTNER_PERMISSION,
    AccessRule.NO_SCRAPING,
    AccessRule.MANUAL_ONLY,
)

# What a source can produce. 'org' and 'rfp' have no record type, matcher or
# writer yet, so a source may declare them and still have nothing to run.
YIELD_KINDS: frozenset[str] = frozenset(
    {"funder", "funder_csr_year", "news_mention", "news_link", "org", "rfp"}
)


@dataclass(frozen=True, slots=True)
class Source:
    key: str
    name: str
    host: str
    """Empty for a class of sites ("NGO official websites") rather than one host."""
    access_rule: AccessRule
    basis: str
    """Why this rule applies — the evidence, not a restatement of the rule."""
    categories: frozenset[Category]
    yields: tuple[str, ...]
    robots_checked_at: date | None = None
    allowed_paths: tuple[str, ...] = ()
    """Path-scoped only. Ending in "/" is a prefix that needs a segment below it; otherwise exact."""
    allowed_query: tuple[tuple[str, str | None], ...] = ()
    """Path-scoped only: the query keys allowed, each with its one required value or None for any."""
    governs_paths: tuple[str, ...] = ()
    """A refusing entry that governs only these paths on its host (any case, any ref after '/' or '@')."""

    @property
    def dispatchable(self) -> bool:
        return self.access_rule in DISPATCHABLE

    @property
    def is_site_class(self) -> bool:
        return not self.host

    @property
    def path_scoped(self) -> bool:
        return self.access_rule in PATH_SCOPED

    def claims_path(self, path: str) -> bool:
        """Whether this entry governs a normalised path. Not whether it may be read: see path_refusal."""
        return any(path.startswith(p) and len(path) > len(p) if p.endswith("/") else path == p
                   for p in self.allowed_paths)

    def governs(self, path: str) -> bool:
        """Whether this entry applies to the path; an entry without governs_paths covers its whole host."""
        p = path.lower()
        return not self.governs_paths or any(p == g or p.startswith((g + "/", g + "@")) for g in self.governs_paths)

    def path_refusal(self, url: str) -> str | None:
        """None when this path-scoped source may read the URL, else why not. Default refuse."""
        parts = urlsplit(url)
        if parts.scheme != "https":
            return "only https is read on this source"
        if parts.username is not None or parts.password is not None:
            return "a URL carrying a user name or password is not read"
        try:
            if parts.port is not None:
                return "a URL naming a port is not read"
        except ValueError:
            return "a URL naming a port is not read"
        if url_host(url) != self.host:
            return f"only {self.host} itself is read under this entry"
        path, why = normal_path(parts.path)
        if why:
            return why
        if ";" in path:
            return "the path carries ';', so it is not read"
        if path != unquote(parts.path or "/"):
            return "the path carries '.', '..' or '//', so it is not read; ask for its normal form"
        if _SIGN_IN_SEGMENTS & {seg.lower() for seg in path.split("/")}:
            return "it is a sign-in or account page, and nothing behind a sign-in is read"
        if not self.claims_path(path):
            return f"only {', '.join(self.allowed_paths)} may be read on {self.host}"
        allowed = dict(self.allowed_query)
        given = parse_qsl(parts.query, keep_blank_values=True)
        keys = [k for k, _ in given]
        if len(set(keys)) != len(keys):
            return "a repeated query parameter is not read"
        for key, value in given:
            if key not in allowed:
                return f"the query parameter {key!r} is not one this source allows"
            if allowed[key] is not None and value != allowed[key]:
                return f"{key} must be {allowed[key]!r} here"
        missing = [k for k, v in allowed.items() if v is not None and k not in keys]
        if missing:
            return f"{', '.join(missing)} must be given, pinned to {', '.join(repr(allowed[k]) for k in missing)}"
        return None


def normal_host(host: str | None) -> str:
    """Lower-case, no trailing dot, no www.: the form registry hosts are written in."""
    return (host or "").lower().rstrip(".").removeprefix("www.")


def url_host(url: str) -> str:
    """The host as the fetcher will see it: IDNA-encoded by httpx (so give。do is give.do), then normal_host."""
    try:
        raw = httpx.URL(url).raw_host.decode("ascii")
    except Exception:  # noqa: BLE001 - an unparseable URL is refused by the egress check, not here
        raw = urlsplit(url).hostname or ""
    return normal_host(raw)


def normal_path(raw: str) -> tuple[str, str | None]:
    """(path decoded once, . and .. resolved, // collapsed; the refusal or None). Still-encoded after one
    decode (double encoding), a backslash or a control character is refused."""
    path = unquote(raw or "/")
    if "%" in path or "\\" in path or any(ord(c) < 32 or ord(c) == 127 for c in path):
        return path, "the path is still encoded after one decode, or carries a backslash or control character"
    norm = posixpath.normpath("/" + path.lstrip("/"))
    if path.endswith("/") and norm != "/":
        norm += "/"
    return norm, None


def _load() -> tuple[Source, ...]:
    out: list[Source] = []
    for name in _FILES:
        payload = json.loads((_DATA / name).read_text(encoding="utf-8"))
        for entry in payload["sources"]:
            checked = entry.get("robots_checked_at")
            out.append(
                Source(
                    key=entry["key"],
                    name=entry["name"],
                    host=entry["host"],
                    access_rule=AccessRule(entry["access_rule"]),
                    basis=entry["basis"],
                    categories=frozenset(Category(c) for c in entry["categories"]),
                    yields=tuple(entry["yields"]),
                    robots_checked_at=date.fromisoformat(checked) if checked else None,
                    allowed_paths=tuple(entry.get("allowed_paths", ())),
                    allowed_query=tuple(entry.get("allowed_query", {}).items()),
                    governs_paths=tuple(entry.get("governs_paths", ())),
                )
            )
    return tuple(out)


_SOURCES: tuple[Source, ...] = _load()
SOURCES: MappingProxyType[str, Source] = MappingProxyType({s.key: s for s in _SOURCES})


def dispatchable() -> list[Source]:
    return [s for s in SOURCES.values() if s.dispatchable]


def in_category(category: Category) -> list[Source]:
    return [s for s in SOURCES.values() if category in s.categories]


def sources_on_host(host: str) -> list[Source]:
    """Every registered product on this host, including parent-domain matches."""
    host = normal_host(host)
    return [
        s for s in SOURCES.values()
        if s.host and (host == s.host or host.endswith("." + s.host))
    ]


def rule_for_host(host: str) -> tuple[AccessRule, Source] | None:
    """The STRICTEST rule among the products on this host, and the source stating it.

    mcacdm.nic.in carries three products; csr.gov.in two. Taking the first match
    would let declaration order decide whether a crawler runs.
    """
    found = sources_on_host(host)
    if not found:
        return None
    strictest = max(found, key=lambda s: _STRICTNESS.index(s.access_rule))
    return strictest.access_rule, strictest


def rule_for_url(url: str) -> tuple[AccessRule, Source] | None:
    """The rule governing a URL: a path-scoped entry on exactly this host when it claims the path,
    else the host's strictest other rule. A host with only scoped entries returns one, so it refuses."""
    parts = urlsplit(url)
    host = url_host(url)
    path, why = normal_path(parts.path)
    # A path that is not in normal form is governed by every entry on the host: the strict reading.
    found = [s for s in sources_on_host(host) if why is not None or s.governs(path)]
    if not found:
        return None
    scoped = [s for s in found if s.path_scoped and s.host == host]
    if why is None:
        for source in scoped:
            if source.claims_path(path):
                return source.access_rule, source
    rest = [s for s in found if not s.path_scoped] or scoped or found
    strictest = max(rest, key=lambda s: _STRICTNESS.index(s.access_rule))
    return strictest.access_rule, strictest


def resolve(keys: list[str] | None) -> tuple[list[Source], list[str]]:
    """Split requested keys into known sources and unknown names."""
    if not keys:
        return list(SOURCES.values()), []
    known, unknown = [], []
    for k in keys:
        (known.append(SOURCES[k]) if k in SOURCES else unknown.append(k))
    return known, unknown


def _self_check() -> None:
    """Fail at import if the inventory contradicts itself."""
    seen: dict[str, str] = {}
    for source in _SOURCES:
        if source.key in seen:
            raise ValueError(f"duplicate source key {source.key!r}")
        seen[source.key] = source.name
        if len(source.basis) <= 40:
            raise ValueError(f"{source.key}: basis is a verdict, not evidence — {source.basis!r}")
        if not source.categories:
            raise ValueError(f"{source.key}: belongs to no category")
        unknown = sorted(set(source.yields) - YIELD_KINDS)
        if unknown:
            raise ValueError(f"{source.key}: unknown yield kinds {unknown}")
        if source.host and (" " in source.host or "/" in source.host):
            raise ValueError(f"{source.key}: {source.host!r} is not a bare host")
        # A dispatchable source is one a crawler will actually visit, so it must
        # name a host and carry the date someone checked its rules.
        if source.dispatchable and not source.host:
            raise ValueError(f"{source.key}: dispatchable but names no host")
        if source.dispatchable and source.robots_checked_at is None:
            raise ValueError(f"{source.key}: dispatchable but nobody recorded a robots check")
        if source.path_scoped:
            if not source.host or not source.allowed_paths:
                raise ValueError(f"{source.key}: a path-scoped source names one host and the paths it reads")
            if source.robots_checked_at is None:
                raise ValueError(f"{source.key}: path-scoped but nobody recorded a robots check")
            for p in source.allowed_paths:
                if p == "/" or normal_path(p) != (p, None):
                    raise ValueError(f"{source.key}: {p!r} is not a normal path below the root")
        elif source.allowed_paths or source.allowed_query:
            raise ValueError(f"{source.key}: allowed_paths and allowed_query belong to path-scoped sources only")
        if source.governs_paths and (source.dispatchable or source.path_scoped or not source.host
                                     or any(normal_path(g) != (g, None) or g.endswith("/") or g != g.lower()
                                            for g in source.governs_paths)):
            raise ValueError(f"{source.key}: governs_paths is for a refusing entry on one host, lower-case normal paths")


_self_check()
