"""The only entity and relationship types the knowledge graph holds; anything else is dropped at extraction."""

from __future__ import annotations

from pydantic import BaseModel, Field

DEFAULT_GROUP = "sangam"  # the catalog is synced here, so documents added here merge into Sangam's own records


class Organization(BaseModel):
    """A civil-society organisation that delivers work on the ground: an NGO, CSO, trust, society, Section 8
    company, cooperative, self-help group federation or community institution. Not a body whose main role is
    giving money (that is a Funder), not a government body, not a for-profit company."""

    org_kind: str | None = Field(None, description="ngo, trust, society, section8, cooperative, cbo or other")


class Funder(BaseModel):
    """A non-government body that gives money to organisations or programmes: a company's CSR arm, a
    philanthropic foundation, a grant-making trust, or a bilateral or multilateral agency."""

    funder_kind: str | None = Field(None, description="csr, foundation, trust, bilateral, multilateral or other")


class GovernmentBody(BaseModel):
    """A part of government: a ministry, department, state mission or society (e.g. a State Rural Livelihood
    Mission), district administration, municipality or panchayat. Not the scheme it runs (that is a Scheme)."""

    level: str | None = Field(None, description="central, state, district or local")


class Location(BaseModel):
    """A place someone works in or is registered in: a country, an Indian state or union territory, a
    district, block, city or village. Not a street address, building, office or venue."""

    level: str | None = Field(None, description="country, state, district, block, city or village")
    state: str | None = Field(None, description="the Indian state it is in, for a district, block or village")


class Program(BaseModel):
    """A named programme or project an organisation, funder or government body runs, e.g. "Read India".
    Not a government scheme (that is a Scheme), a one-off event, a report, or a generic activity like "training"."""

    status: str | None = Field(None, description="active, completed or planned")


class Scheme(BaseModel):
    """A government scheme or national mission, named exactly as in Sangam's taxonomy, e.g. "DAY-NRLM" or
    "PMKVY (Skill India)". Something the taxonomy does not name is not a Scheme."""


class Theme(BaseModel):
    """A development sector or theme an organisation, funder or programme works on, named exactly as in
    Sangam's taxonomy (a domain, a theme or a sub-theme). Something the taxonomy does not name is not a Theme."""


class PopulationGroup(BaseModel):
    """A group of people the work serves, named exactly as in Sangam's taxonomy, e.g. women, children,
    tribal communities, persons with disabilities. Something the taxonomy does not name is not a PopulationGroup."""


class Person(BaseModel):
    """A named founder, director, CEO, trustee or programme lead of an organisation or funder. Not
    beneficiaries, authors, staff without a leadership role, or anyone named only in passing."""

    role: str | None = Field(None, description="their role, e.g. founder, CEO, trustee")


class Funds(BaseModel):
    """A funder, government body or intermediary organisation gives money to an organisation or a programme."""

    amount_inr: float | None = Field(None, description="amount in rupees; convert lakh and crore")
    fiscal_year: str | None = Field(None, description="e.g. FY2023-24")


class PartnersWith(BaseModel):
    """Two bodies work together: implementing partners, co-funders, or an organisation working with a
    government body or a funder beyond a grant."""


class Runs(BaseModel):
    """An organisation, funder or government body runs a programme, or a government body runs a scheme."""


class Implements(BaseModel):
    """An organisation, funder or programme implements or converges with a government scheme."""


class WorksIn(BaseModel):
    """An organisation, funder, government body or programme is based in or works in a place."""

    role: str | None = Field(None, description="headquartered for a head or registered office, operates for "
                                               "where the work happens")


class FocusesOn(BaseModel):
    """An organisation, funder or programme works on a theme."""


class Serves(BaseModel):
    """An organisation, funder or programme serves a group of people."""

    reach: str | None = Field(None, description="how many it reaches, as stated, e.g. 12,000 households")


class LocatedIn(BaseModel):
    """A place lies inside a larger place: a district in a state, a state in a country."""


class PartOf(BaseModel):
    """A theme lies inside a broader one: a sub-theme in a theme, a theme in a domain."""


class Leads(BaseModel):
    """A person leads, founded or governs an organisation or funder."""

    role: str | None = Field(None, description="their role, e.g. founder, CEO, trustee")


ENTITY_TYPES: dict[str, type[BaseModel]] = {
    "Organization": Organization,
    "Funder": Funder,
    "GovernmentBody": GovernmentBody,
    "Program": Program,
    "Scheme": Scheme,
    "Location": Location,
    "Theme": Theme,
    "PopulationGroup": PopulationGroup,
    "Person": Person,
}

# Taxonomy-backed types: the model picks from a fixed list, and a pick the taxonomy lacks is labelled Unmapped.
CLOSED_TYPES = ("Theme", "Scheme", "PopulationGroup")

EDGE_TYPES: dict[str, type[BaseModel]] = {
    "FUNDS": Funds,
    "PARTNERS_WITH": PartnersWith,
    "RUNS": Runs,
    "IMPLEMENTS": Implements,
    "WORKS_IN": WorksIn,
    "FOCUSES_ON": FocusesOn,
    "SERVES": Serves,
    "LOCATED_IN": LocatedIn,
    "PART_OF": PartOf,
    "LEADS": Leads,
}

_BODIES = ("Organization", "Funder", "GovernmentBody")
_PARTNERS = {(a, b): ["PARTNERS_WITH"] for a in _BODIES for b in _BODIES}

EDGE_TYPE_MAP: dict[tuple[str, str], list[str]] = {
    **_PARTNERS,
    ("Funder", "Organization"): ["FUNDS", "PARTNERS_WITH"],
    ("GovernmentBody", "Organization"): ["FUNDS", "PARTNERS_WITH"],
    ("Organization", "Organization"): ["FUNDS", "PARTNERS_WITH"],
    ("Funder", "Program"): ["FUNDS", "RUNS"],
    ("GovernmentBody", "Program"): ["FUNDS", "RUNS"],
    ("Organization", "Program"): ["FUNDS", "RUNS"],
    ("GovernmentBody", "Scheme"): ["RUNS"],
    ("Organization", "Scheme"): ["IMPLEMENTS"],
    ("Funder", "Scheme"): ["IMPLEMENTS"],
    ("Program", "Scheme"): ["IMPLEMENTS"],
    ("Organization", "Location"): ["WORKS_IN"],
    ("Funder", "Location"): ["WORKS_IN"],
    ("GovernmentBody", "Location"): ["WORKS_IN"],
    ("Program", "Location"): ["WORKS_IN"],
    ("Organization", "Theme"): ["FOCUSES_ON"],
    ("Funder", "Theme"): ["FOCUSES_ON"],
    ("Program", "Theme"): ["FOCUSES_ON"],
    ("Organization", "PopulationGroup"): ["SERVES"],
    ("Funder", "PopulationGroup"): ["SERVES"],
    ("Program", "PopulationGroup"): ["SERVES"],
    ("Location", "Location"): ["LOCATED_IN"],
    ("Theme", "Theme"): ["PART_OF"],
    ("Person", "Organization"): ["LEADS"],
    ("Person", "Funder"): ["LEADS"],
}

INSTRUCTIONS = """\
Extract ONLY these kinds of entity: Organization, Funder, GovernmentBody, Program, Scheme, Location, Theme,
PopulationGroup, Person. Anything that fits none of them is not an entity: skip reports, sections, tables,
metrics, dates, money amounts, documents, events, products, generic nouns ("beneficiaries", "the project")
and acronyms you cannot expand.
- Use each entity's full official name: "Pratham Education Foundation", not "Pratham" or "the Foundation",
  when the full name appears anywhere in the text.
- A company's CSR arm, or a foundation or trust that gives grants, is a Funder, even if it also runs
  programmes itself.
- A ministry, department, state mission or society (e.g. "Assam State Rural Livelihood Mission"), district
  administration or panchayat is a GovernmentBody, never an Organization or a Funder. The national scheme it
  carries out (e.g. DAY-NRLM) is a Scheme.
- A Scheme is one of these, spelt exactly as listed: {schemes}.
- A Theme is one of these, spelt exactly as listed, the most specific that fits: {themes}. Work that fits
  none of them is not a Theme.
- A PopulationGroup is one of these, spelt exactly as listed: {populations}. "Women farmers" serves women.
  Put how many are reached (e.g. "12,000 households") on SERVES as reach.
- Locations are countries, Indian states and union territories, districts, blocks, cities and villages. Use
  current spellings (Odisha, not Orissa). Never a street address or a building. On WORKS_IN set role:
  headquartered for a head or registered office, operates for where the work happens.
- Money is never an entity: put an amount on the FUNDS relationship, in rupees (1 lakh = 100000,
  1 crore = 10000000).
- An implementing partner of a funder PARTNERS_WITH it; a grant is FUNDS. Both may hold.
- A Person is only a named leader (founder, director, CEO, trustee, programme lead) of an organisation or funder.
Relationships may only be FUNDS, PARTNERS_WITH, RUNS, IMPLEMENTS, WORKS_IN, FOCUSES_ON, SERVES, LOCATED_IN,
PART_OF or LEADS, between the entity kinds their descriptions name. Do not record any other kind."""

OPEN_LIST = {
    "Theme": "any recognised development sector",
    "Scheme": "any named government scheme or national mission",
    "PopulationGroup": "any clearly named group, such as women, children or tribal communities",
}
PLACEHOLDER = {"Theme": "{themes}", "Scheme": "{schemes}", "PopulationGroup": "{populations}"}


def instructions(vocabulary: dict[str, list[str]]) -> str:
    text = INSTRUCTIONS
    for kind, placeholder in PLACEHOLDER.items():
        labels = vocabulary.get(kind) or []
        text = text.replace(placeholder, ", ".join(labels) if labels else OPEN_LIST[kind])
    return text


def entity_type(labels: list[str]) -> str | None:
    return next((label for label in labels if label in ENTITY_TYPES), None)


def edge_allowed(name: str, source_labels: list[str], target_labels: list[str]) -> bool:
    return name in EDGE_TYPE_MAP.get((entity_type(source_labels), entity_type(target_labels)), [])


def extraction_kwargs(vocabulary: dict[str, list[str]]) -> dict:
    """What every add_episode call passes, so documents, episodes and the catalog share one ontology."""
    return {
        "entity_types": ENTITY_TYPES,
        "excluded_entity_types": ["Entity"],
        "edge_types": EDGE_TYPES,
        "edge_type_map": EDGE_TYPE_MAP,
        "custom_extraction_instructions": instructions(vocabulary),
    }
