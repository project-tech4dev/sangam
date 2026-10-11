"""Filing a funder's own words for a theme under a Schedule VII clause.

Schedule VII is a closed statutory list of twelve activities, which is what
makes normalising against it safe: the categories are not ours to invent, and
a spend that fits none of them is a spend whose clause we do not know.

The mapping is a keyword table rather than a model call, for the reason the
whole importer exists: "Building Human Capital" is not Education until someone
decides it is, and a decision made in a prompt is a decision nobody can review.
Anything that does not match leaves `csr_sector_id` NULL, with the funder's
wording kept on the row — which is what happened to every spend row before
this existed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# slug -> the words that place a theme under that clause. Ordered most
# specific first: 'skill' must reach education before 'development' reaches
# rural development.
CLAUSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("csr-education-and-livelihoods",
     ("education", "school", "scholarship", "literacy", "vocational", "skilling",
      "skill development", "livelihood", "employability", "training", "teacher")),
    ("csr-hunger-poverty-health",
     ("health", "healthcare", "hospital", "medical", "nutrition", "malnutrition",
      "hunger", "poverty", "sanitation", "drinking water", "wash", "hygiene",
      "immunis", "immuniz", "maternal", "thalassemia", "cancer", "eye care")),
    ("csr-gender-equality-and-inequality",
     ("gender", "women", "girl child", "orphanage", "old age", "elderly",
      "inequality", "empowerment of women", "widow")),
    ("csr-environment-and-animal-welfare",
     ("environment", "ecolog", "biodiversity", "afforest", "agroforest", "plantation",
      "animal welfare", "conservation", "climate", "renewable", "solar", "clean energy")),
    ("csr-national-heritage-art-culture",
     ("heritage", "art and culture", "culture", "handicraft", "museum", "monument")),
    ("csr-armed-forces-veterans", ("armed forces", "veteran", "war widow", "ex-servicemen")),
    ("csr-sports", ("sport", "olympic", "paralympic", "athlete")),
    ("csr-central-government-funds",
     ("pm cares", "prime minister", "national relief fund", "swachh bharat kosh",
      "clean ganga fund")),
    ("csr-technology-incubators-and-rnd",
     ("incubator", "research and development", "r&d", "innovation", "technology incubat")),
    ("csr-slum-area-development", ("slum",)),
    ("csr-disaster-management",
     ("disaster", "relief", "rehabilitation", "flood", "cyclone", "earthquake", "pandemic")),
    # Last: 'rural development' is the clause a great many themes mention in
    # passing, so a more specific match should win first.
    ("csr-rural-development",
     ("rural development", "rural infrastructure", "village", "rural")),
)


def clause_for(text: str | None) -> str | None:
    """The Schedule VII slug a theme belongs to, or None when it is not clear."""
    if not text:
        return None
    lowered = text.lower()
    for slug, keywords in CLAUSES:
        if any(word in lowered for word in keywords):
            return slug
    return None


async def resolve_csr_sector(conn: Any, text: str | None) -> int | None:
    """The tags row for a theme. None when the words do not place it, or when
    the Schedule VII vocabulary has not been seeded (`make taxonomy-seed`)."""
    slug = clause_for(text)
    if slug is None:
        return None
    row = await (
        await conn.execute(
            "SELECT id FROM tags WHERE slug = %s AND kind = 'csr_sector'", (slug,)
        )
    ).fetchone()
    return row["id"] if row else None


# The five domains (D6), defined here once.
DOMAINS = ("livelihoods", "health", "education", "environment", "others")


async def resolve_classification(
    conn: Any, domain: str | None, theme: str | None
) -> tuple[int | None, int | None, list[str]]:
    """(domain_tag_id, theme_tag_id, reasons) for an inferred classification (D11). Holds back, never
    guesses: a bad domain holds the line; a bad theme is dropped with a reason and the line keeps its domain."""
    if not domain:
        return None, None, []
    if domain not in DOMAINS:
        return None, None, [
            f"domain {domain!r} is not one of {', '.join(DOMAINS)}, so the line is not written"
        ]
    row = await (
        await conn.execute(
            "SELECT id FROM tags WHERE kind = 'domain' AND code = %s AND status <> 'deprecated'",
            (domain,),
        )
    ).fetchone()
    if row is None:
        return None, None, [(
            f"domain {domain!r} is not in tags, so the line is not written. Run `make taxonomy-seed`: "
            "the five domains come from seed/data/taxonomy/themes.json"
        )]
    if not theme:
        return row["id"], None, []
    rows = await (
        await conn.execute(
            "SELECT id, domain FROM tags WHERE kind IN ('theme', 'sub_theme') AND code = %s "
            "AND status <> 'deprecated' ORDER BY id LIMIT 2",
            (theme,),
        )
    ).fetchall()
    if len(rows) != 1:
        what = "is ambiguous" if rows else "is not in the taxonomy"
        return row["id"], None, [f"theme {theme!r} {what}; the line is written with its domain and no theme"]
    if rows[0]["domain"] != domain:
        return row["id"], None, [(
            f"theme {theme!r} belongs to {rows[0]['domain']!r}, not {domain!r}; the line is written "
            "with its domain and no theme"
        )]
    return row["id"], rows[0]["id"], []


# The tag vocabulary a finding may use: copies of seed/data/taxonomy, since the deployed backend has no seed/.
_DATA = Path(__file__).parent / "data"


def _vocabulary() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Per tag list, code -> what the researcher reads beside it, and code -> its tags.slug (seed.taxonomy_seed's
    `<kind>-<code>`, the unique key the writer resolves on)."""
    themes = json.loads((_DATA / "themes.json").read_text(encoding="utf-8"))
    common = json.loads((_DATA / "common.json").read_text(encoding="utf-8"))
    labels: dict[str, dict[str, str]] = {"themes": {}, "populations": {}, "lenses": {}}
    slugs: dict[str, dict[str, str]] = {"themes": {}, "populations": {}, "lenses": {}}
    for d in themes["domains"]:
        for t in d["themes"]:
            labels["themes"][t["code"]] = f"{t['label']} (a theme in {d['label']})"
            slugs["themes"][t["code"]] = f"theme-{t['code']}"
            for sub in t["sub_themes"]:
                labels["themes"][sub["code"]] = f"{sub['label']} (under {t['code']})"
                slugs["themes"][sub["code"]] = f"sub_theme-{sub['code']}"
    for code, label in common["population"]:
        labels["populations"][code], slugs["populations"][code] = label, f"population-{code}"
    for lens in themes["lenses"]:
        labels["lenses"][lens["code"]], slugs["lenses"][lens["code"]] = lens["label"], f"lens-{lens['code']}"
    return labels, slugs


VOCABULARY, TAG_SLUGS = _vocabulary()
THEME_CODES, POPULATION_CODES, LENS_CODES = (tuple(VOCABULARY[k]) for k in ("themes", "populations", "lenses"))
# Tag kind for each list a finding carries; a theme code is a theme or a sub-theme.
TAG_KINDS: dict[str, tuple[str, ...]] = {
    "themes": ("theme", "sub_theme"), "populations": ("population",), "lenses": ("lens",),
}
