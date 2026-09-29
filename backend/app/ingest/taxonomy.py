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
