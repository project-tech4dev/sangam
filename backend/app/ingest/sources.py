"""The sources Sangam may read, and the rule that governs each one."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType


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


# A crawler may run only for these. Everything else is reported as refused, with
# its basis, so an unsupported source is a row in the summary and not a silence.
DISPATCHABLE: frozenset[AccessRule] = frozenset({AccessRule.OPEN_API, AccessRule.CRAWL_ALLOWED})


@dataclass(frozen=True, slots=True)
class Source:
    key: str
    name: str
    host: str
    access_rule: AccessRule
    basis: str
    """Why this rule applies — the evidence, not a restatement of the rule."""
    yields: tuple[str, ...]
    """Record kinds the adapter can emit."""
    robots_checked_at: date | None = None
    entity: str = "funder"

    @property
    def dispatchable(self) -> bool:
        return self.access_rule in DISPATCHABLE


_CHECKED = date(2026, 9, 28)

_SOURCES: tuple[Source, ...] = (
    Source(
        key="india_csr",
        name="India CSR",
        host="indiacsr.in",
        access_rule=AccessRule.CRAWL_ALLOWED,
        basis="robots.txt disallows only /wp-admin/ and publishes a sitemap; read through the "
        "site's own WordPress REST API rather than by parsing pages.",
        yields=("funder", "funder_csr_year"),
        robots_checked_at=_CHECKED,
    ),
    Source(
        key="gdelt",
        name="GDELT DOC 2.0 (funders_grants)",
        host="api.gdeltproject.org",
        access_rule=AccessRule.OPEN_API,
        basis="Free public API offered for reuse; GDELT is cited on every row it produces.",
        yields=("news_mention",),
        robots_checked_at=_CHECKED,
    ),
    # Registered deliberately. It is a real funder source and it must never be
    # crawled, so the run reports it as refused instead of quietly skipping it.
    Source(
        key="give",
        name="Give (funder profiles)",
        host="give.do",
        access_rule=AccessRule.NO_SCRAPING,
        basis="Give's terms bar data mining and limit content to non-commercial use. "
        "Manual entry with a source link stays allowed; a crawler needs Give's written permission.",
        yields=("funder",),
        robots_checked_at=_CHECKED,
    ),
    Source(
        key="mca_csr",
        name="MCA CSR Data (Dynamic CSR Report)",
        host="mcacdm.nic.in",
        access_rule=AccessRule.NO_SCRAPING,
        basis="robots.txt disallows automated access; the site also answers 503 outside India. "
        "Manual export from an Indian network, or Dataful's licensed mirror.",
        yields=("funder", "funder_csr_year"),
        robots_checked_at=_CHECKED,
    ),
    Source(
        key="csrbox",
        name="CSRBOX",
        host="csrbox.org",
        access_rule=AccessRule.CRAWL_WITH_PERMISSION,
        basis="No robots.txt and no scraping clause found, but the listings are the operator's "
        "curated product. Ask for permission or a feed first.",
        yields=("funder",),
        robots_checked_at=_CHECKED,
    ),
)

SOURCES: MappingProxyType[str, Source] = MappingProxyType({s.key: s for s in _SOURCES})


def dispatchable() -> list[Source]:
    return [s for s in SOURCES.values() if s.dispatchable]


def resolve(keys: list[str] | None) -> tuple[list[Source], list[str]]:
    """Split requested keys into known sources and unknown names."""
    if not keys:
        return list(SOURCES.values()), []
    known, unknown = [], []
    for k in keys:
        (known.append(SOURCES[k]) if k in SOURCES else unknown.append(k))
    return known, unknown
