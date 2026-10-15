"""proposal-v2: what each section asks, what a strong answer holds, and the order sections are written in.

Pure: no pool, no async, no settings. Codes are storage only; the screen shows labels.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

RUBRIC_VERSION = "proposal-v2"

Tab = Literal["case", "people", "money", "funder"]

# Step 3's four tabs, in screen order, as the prototype names them.
TABS: list[tuple[Tab, str]] = [
    ("case", "The case and the plan"),
    ("people", "People"),
    ("money", "Durability and money"),
    ("funder", "This funder"),
]

MUST_SCORE_2 = ("A6", "A15", "F1")


@dataclass(frozen=True)
class Section:
    code: str
    label: str
    question: str
    tab: Tab
    strong: tuple[str, ...]
    weak: str

    def out(self) -> dict[str, Any]:
        return {**asdict(self), "strong": list(self.strong), "must_score_2": self.code in MUST_SCORE_2,
                "last": self.code == "A1"}


def _s(code: str, label: str, question: str, tab: Tab, strong: list[str], weak: str) -> Section:
    return Section(code, label, question, tab, tuple(strong), weak)


# In screen order; A1 is listed first but written last (DEPENDS_ON).
CORE: list[Section] = [
    _s("A1", "Summary", "Can I repeat this project in two sentences?", "case",
       ["The problem", "The site and community", "The objective", "Two or three results with numbers",
        "The amount and the duration"], "Mission statement or activity list with no numbers or place"),
    _s("A2", "Context and target area", "Do I know exactly where this happens and who lives there?", "case",
       ["State, district, block and villages", "Population and livelihoods", "Existing community institutions",
        "A source for each fact"], "General description of the state or region"),
    _s("A3", "Problem and baseline", "Is the problem real, local and measured?", "case",
       ["The specific problem at the site", "Current figures with source and year", "The causes the project will act on"],
       "Broad claims about poverty or climate with no local data"),
    _s("A4", "Objectives and results", "What will be different at the end, and by how much?", "case",
       ["Objectives stated as changes", "Results as numbers with units", "Each result linked to an objective"],
       "Objectives written as activities; results with no numbers"),
    _s("A5", "Activities and workplan", "Can this team deliver this sequence in this time?", "case",
       ["Activities grouped under results", "An owner, target and timing for each", "Reviews and reports scheduled"],
       "Activities listed with no timing, owner or target"),
    _s("A6", "Indicators and M&E", "How will we know it worked?", "case",
       ["Indicators for each result", "Baseline, target, source and frequency", "A named owner",
        "Mid-term and final reviews"], "Indicators that only count activities"),
    _s("A7", "Learning and knowledge sharing", "What will others learn from this?", "case",
       ["Named knowledge products", "Who each is for", "How each will be shared"], "One line promising a report"),
    _s("A8", "Community participation", "Did the community shape this, and will they steer it?", "people",
       ["Consultations held, with dates and numbers", "Community roles in delivery and monitoring",
        "Minutes or resolutions attached"], "A statement that the community will be involved"),
    _s("A9", "Inclusion", "Who could be left out, and what stops that?", "people",
       ["Targets for women, youth, persons with disabilities as relevant", "Their roles in decisions",
        "Budget lines that pay for it"], "Women counted only as attendees; nothing in the budget"),
    _s("A10", "Team and organisational capacity", "Who exactly does the work?", "people",
       ["Named staff with role, qualifications and years", "Structure, governance and finance systems"],
       "Team described as experienced professionals with no names"),
    _s("A11", "Track record", "Has this organisation done this before, and what changed?", "people",
       ["Comparable past projects", "Funder, amount, place and duration", "Results in numbers"],
       "Project names or partner logos with no results"),
    _s("A12", "Partnerships", "Who else is involved, and doing what?", "people",
       ["Each partner named with its role", "A letter or MoU for each"], "A list of names with no roles"),
    _s("A13", "Risks and mitigation", "What could stop this working?", "money",
       ["Internal and external risks specific to this project", "A concrete mitigation for each"],
       "Generic risks answered with 'we will monitor'"),
    _s("A14", "Sustainability and exit", "What happens the day the grant ends?", "money",
       ["Who runs the work after", "How it is paid for", "Handover steps before, during and at the end"],
       "A statement that community institutions will sustain it"),
    _s("A15", "Budget", "Does every rupee trace to an activity?", "money",
       ["Every line tied to an activity", "Unit costs shown", "Totals consistent across sections",
        "Within the funder's ceiling"], "Lump sums; totals that differ"),
    _s("A16", "Other funding", "Who else is paying, and is it real?", "money",
       ["Each source with its amount", "Cash or in-kind, committed or projected", "Proof attached"],
       "Other funding claimed with no source or status"),
]

F1 = _s("F1", "Fit with funder priorities", "Does this serve what this funder is trying to do?", "funder",
        ["Names the funder's programme or theme", "Explains the link", "Names related schemes it builds on"],
        "Claims to fit every priority")
# Only when the org has an earlier partner line with this funder.
F4 = _s("F4", "Earlier phase results", "What did the last phase achieve, and what was learned?", "funder",
        ["Outputs, outcomes and impact of the earlier phase", "Its financial assessment", "Lessons applied now"],
        "Claims of success with no assessment")

# A section is written only once these are written; A1 waits for every other section.
DEPENDS_ON: dict[str, tuple[str, ...]] = {"A4": ("A2", "A3"), "A5": ("A4",), "A6": ("A4",), "A15": ("A5",)}


def default_style(org: str) -> str:
    return (f"Plain, specific English for a CSR programme officer who reads many proposals. Short sentences, active "
            f"voice, third person (\"{org} will…\"). Open each section with its strongest fact or number. Name places, "
            "groups and dates; no jargon, slogans or superlatives. Money in ₹ with lakh and crore; every figure with "
            "its source and year.")


def sections_for(earlier_phase: bool, template: dict[str, Any] | None = None) -> list[Section]:
    """Every section: the rubric's, F4 after an earlier phase, then the form's own questions under This funder."""
    out = [*CORE, F1, *([F4] if earlier_phase else [])]
    questions = (template or {}).get("questions") or {}
    return [*out, *(_s(code, q.get("label") or code, q.get("ask") or "", "funder", [], "")
                    for code, q in questions.items())]


def depends_on(code: str, codes: list[str]) -> tuple[str, ...]:
    """What must be written before `code`; A1 needs every other section."""
    if code == "A1":
        return tuple(c for c in codes if c != "A1")
    return DEPENDS_ON.get(code, ())


def is_core(code: str) -> bool:
    return code.startswith("A")


def score(missing: list[str]) -> int:
    """None missing scores 2, one missing 1, more 0."""
    return 2 if not missing else 1 if len(missing) == 1 else 0
