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
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from importlib.resources import files
from types import MappingProxyType

_DATA = files("app.ingest") / "data" / "sources"
_FILES = ("funders.json", "ngos.json", "rfps.json", "media.json")


class AccessRule(StrEnum):
    """The legend from the source inventory. Only the first two are dispatchable."""

    OPEN_API = "open_api"
    CRAWL_ALLOWED = "crawl_allowed"
    CRAWL_PER_SITE = "crawl_allowed_check_each_site"
    CRAWL_WITH_PERMISSION = "crawl_only_with_permission"
    NO_SCRAPING = "no_scraping_manual_entry_allowed"
    MANUAL_ONLY = "manual_entry_only_automation_blocked"
    LICENCE_NEEDED = "licence_or_paid_access_needed"
    PARTNER_PERMISSION = "partner_permission_internal"
    REFERENCE_ONLY = "reference_only"
    NOT_CHECKED = "not_checked"


class Category(StrEnum):
    FUNDER = "funder"
    NGO = "ngo"
    RFP = "rfp"
    MEDIA = "media"


# A crawler may run only for these. Everything else is reported as refused, with
# its basis, so an unsupported source is a row in the summary and not a silence.
DISPATCHABLE: frozenset[AccessRule] = frozenset({AccessRule.OPEN_API, AccessRule.CRAWL_ALLOWED})

# Ordered permissive → restrictive. When several products share a host the
# strictest wins, so a permissive product can never unlock a restricted one.
_STRICTNESS: tuple[AccessRule, ...] = (
    AccessRule.OPEN_API,
    AccessRule.CRAWL_ALLOWED,
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
    {"funder", "funder_csr_year", "news_mention", "org", "rfp"}
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

    @property
    def dispatchable(self) -> bool:
        return self.access_rule in DISPATCHABLE

    @property
    def is_site_class(self) -> bool:
        return not self.host


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
    host = host.lower().removeprefix("www.")
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


_self_check()
