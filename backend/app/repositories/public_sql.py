"""SQL pieces the public Registry reads share: the profile pages and the list say the same thing by construction.

Every URL a public query selects goes through public_url, the SQL form of source_guards.is_private_source."""

from __future__ import annotations

from app.ingest.source_guards import PRIVATE_SOURCE_DOMAIN

# The host after an optional scheme and userinfo, lower-cased and without a trailing dot.
_HOST_RE = r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:)?(?://)?(?:[^@/?#]*@)?([^/:?#]+)"
_SUFFIX = "." + PRIVATE_SOURCE_DOMAIN


def host_of(col: str) -> str:
    return f"rtrim(lower(substring({col} from '{_HOST_RE}')), '.')"


def is_private_url(col: str) -> str:
    """True for a private host; stricter than the Python check only for a scheme-less "x.sangam.invalid"."""
    host = host_of(col)
    return (f"coalesce({host} = '{PRIVATE_SOURCE_DOMAIN}' "
            f"OR right({host}, {len(_SUFFIX)}) = '{_SUFFIX}', false)")


def public_url(col: str) -> str:
    return f"CASE WHEN {is_private_url(col)} THEN NULL ELSE {col} END"


def public_name(name_col: str, url_col: str) -> str:
    """A source's name is as private as its link: a staff sheet's title names the sheet."""
    return f"CASE WHEN {is_private_url(url_col)} THEN NULL ELSE {name_col} END"


def public_text(col: str) -> str:
    """Free text (a note, a quote) that names a private source is dropped whole."""
    return f"CASE WHEN strpos(lower({col}), '{PRIVATE_SOURCE_DOMAIN}') > 0 THEN NULL ELSE {col} END"


def source(alias: str) -> str:
    """`source_name, source_url` of one row, both public."""
    return (f"{public_name(f'{alias}.source_name', f'{alias}.source_url')} AS source_name, "
            f"{public_url(f'{alias}.source_url')} AS source_url")


# A location's state: itself when it is one, its parent when it is a district. Needs aliases l and lp.
STATE_OF = "CASE l.kind WHEN 'state' THEN l.name WHEN 'district' THEN lp.name END"

# An open call still taking applications, on rfps aliased r.
OPEN_CALL = "r.status = 'open' AND (r.deadline IS NULL OR r.deadline >= current_date)"


def research_match(kind: str, entity_id: str, slug: str) -> str:
    """An entity_research row (alias r) about this org or funder: resolved to it, or unresolved under its slug."""
    resolved = (f"CASE {kind} WHEN 'org' THEN r.resolved_org_id ELSE r.resolved_funder_id END")
    return (f"r.status <> 'wrong_entity' AND ({resolved} = {entity_id} "
            f"OR ({resolved} IS NULL AND r.slug = {slug} AND r.entity_kind IN ({kind}, 'unknown')))")


# A story about an entity that clears the public bar, on news_story_entities e and news_stories s.
PUBLIC_STORY = "e.visibility = 'public' AND s.is_news"

# What a story is: a post on a social platform, or press. Needs news_links ml and the %(social)s list.
STORY_CHANNEL = "CASE WHEN ml.source_type = ANY(%(social)s) THEN 'social' ELSE 'press' END"


def story_counts(owner: str) -> str:
    """Press and social counts, and the first post's date, per entity in %(ids)s."""
    return f"""
SELECT e.{owner} AS id,
       count(DISTINCT s.id) FILTER (WHERE {STORY_CHANNEL} = 'press') AS press,
       count(DISTINCT s.id) FILTER (WHERE {STORY_CHANNEL} = 'social') AS social,
       min(coalesce(s.published_on, s.first_seen_at::date)) FILTER (WHERE {STORY_CHANNEL} = 'social') AS posts_since
FROM news_story_entities e
JOIN news_stories s ON s.id = e.story_id
LEFT JOIN news_links ml ON ml.id = s.main_link_id
WHERE e.{owner} = ANY(%(ids)s) AND {PUBLIC_STORY}
GROUP BY 1
"""


def entity_tags(owner: str, table: str) -> str:
    """Each tag of the entities in %(ids)s: its parent's label, its domain, and how many of their programmes carry it."""
    return f"""
WITH RECURSIVE up AS (
  SELECT id AS start, id, parent_id, label, kind FROM tags
  UNION ALL
  SELECT up.start, t.id, t.parent_id, t.label, t.kind FROM tags t JOIN up ON t.id = up.parent_id
),
root AS (SELECT start, label FROM up WHERE parent_id IS NULL AND kind = 'domain')
SELECT x.{owner} AS id, tg.slug, tg.label, tg.kind, x.role, {public_text('x.note')} AS note,
       par.label AS parent_label, root.label AS domain,
       (SELECT count(*) FROM programs p JOIN program_tags pt ON pt.program_id = p.id
        WHERE p.{owner} = x.{owner} AND pt.tag_id = x.tag_id) AS progs
FROM {table} x
JOIN tags tg ON tg.id = x.tag_id
LEFT JOIN tags par ON par.id = tg.parent_id
LEFT JOIN root ON root.start = tg.id
WHERE x.{owner} = ANY(%(ids)s)
ORDER BY x.role, tg.label
"""


def entity_sdgs(owner: str, table: str) -> str:
    """SDGs reached through the entities' tags (tag_links), in the taxonomy's order."""
    return f"""
SELECT x.{owner} AS id, s.code, s.label
FROM {table} x JOIN tag_links tl ON tl.tag_id = x.tag_id
JOIN tags s ON s.id = tl.linked_tag_id AND s.kind = 'sdg'
WHERE x.{owner} = ANY(%(ids)s) AND s.code IS NOT NULL
GROUP BY x.{owner}, s.code, s.label, s.sort_order
ORDER BY 1, s.sort_order NULLS LAST, s.code
"""


# Org registrations as every viewer sees them: a private row is on file, with no number and no detail.
# Read on the owner pool, so RLS gives a member or staff nothing more than anyone else.
IDENTIFIERS = f"""
SELECT org_id, id, id_type, status, is_current, (NOT is_public) AS number_withheld,
       CASE WHEN is_public THEN id_value END AS id_value,
       CASE WHEN is_public THEN application_ref END AS application_ref,
       CASE WHEN is_public THEN valid_from END AS valid_from,
       CASE WHEN is_public THEN valid_until END AS valid_until,
       CASE WHEN is_public THEN check_method END AS check_method,
       is_public AND verified AS verified,
       CASE WHEN is_public THEN source_type END AS source_type,
       CASE WHEN is_public THEN evidence END AS evidence,
       CASE WHEN is_public THEN {public_url('source_url')} END AS source_url,
       CASE WHEN is_public THEN {public_text('notes')} END AS notes
FROM org_identifiers WHERE org_id = ANY(%(ids)s)
ORDER BY org_id, id_type, is_current DESC, (id_value IS NULL), id
"""

# Registrations a list filter counts as on file: current, registered or provisional, public or not.
ON_FILE = "is_current AND status IN ('registered', 'provisional')"
