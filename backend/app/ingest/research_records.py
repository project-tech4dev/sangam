"""What a researcher returns: findings shaped like the rows they become.

A finding used to be a label and a value, both strings, and promote.py bridged
the gap to a relational row with regular expressions — sniffing for the word
"crore" to decide a scale, grepping a label for a fiscal year, keyword-matching
to pick a column. That is how a figure becomes wrong by a factor of ten
million, which this codebase has shipped twice.

So the shape is fixed at the source instead. One model per concept, its fields
taken from the target table's columns (app/ingest/expectations.py derives that
list from the SQL catalog, and a test holds the two together). The writer then
maps rather than parses.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ingest.expectations import CONCEPTS as _REGISTRY
from app.ingest.expectations import RESERVED_DOC_TYPES, concepts_for
from app.ingest.records import (
    CIN_FORMAT,
    ClassifiedBy,
    EvidenceTier,
    FindingSourceType,
    IdentifierStatus,
    ImplementationMode,
    check_registration,
    check_tier,
    fiscal_year_of,
    http_url,
    normalise_cin,
)
from app.ingest.taxonomy import DOMAINS, LENS_CODES, POPULATION_CODES, THEME_CODES

# The vocabulary is the registry's, in its order. A `Concept = Literal[...]`
# alias used to sit here repeating all thirteen; it was imported nowhere.
CONCEPTS: tuple[str, ...] = tuple(_REGISTRY)
FISCAL_YEAR = re.compile(r"^FY\d{4}-\d{2}$")

SCHEMA_VERSION = 3
"""Bumped when the finding shape changes. Version 1 rows are flat label/value
pairs: still readable, not promotable, re-researched rather than migrated."""
TYPED_SINCE = 2
"""The first typed shape. v3 only added fields (page, a document's summary, unplaced), so v2 still promotes."""

_UNITS: dict[str, int] = {"inr": 1, "lakh": 1_00_000, "crore": 1_00_00_000}

DomainCode = Literal[*DOMAINS]



def _hint(codes: tuple[str, ...]) -> dict[str, Any]:
    # The codes reach the schema as a hint, not a check: an invented one is dropped and noted at promotion.
    return {"items": {"type": "string", "examples": list(codes)}}
MAX_THEMES = 3


_CLASSIFIED_FROM = {"project_name": ("project_name", "project"), "filed_sector": ("sector", "filed under"),
                    "partner": ("partner_name", "partner"), "report": ("program_name", "programme")}


def _check_classification(f: Any) -> None:
    """D11: a domain and theme are inferences, and a theme says what it rests on."""
    if not f.theme or (f.classification_note or "").strip():
        return
    # The field classified_by names is the evidence, so the note can quote it rather than refuse.
    field, label = _CLASSIFIED_FROM[f.classified_by]
    if value := (getattr(f, field, None) or "").strip():
        f.classification_note = f"{label} '{value}'"
        return
    raise ValueError(
        "a theme needs a classification_note quoting what it rests on, e.g. "
        "\"project 'Financial Literacy & Inclusion'; filed under Education\""
    )


_NOTE_HELP = ("REQUIRED with a theme: the evidence in a few words. Left empty, it is filled from the field "
              "classified_by names, and the finding is refused if that field is empty too")


def _drop_null_extras(cls: type[BaseModel], data: Any) -> Any:
    """A null under a key the model lacks says nothing, so it is dropped rather than refused."""
    if not isinstance(data, dict):
        return data
    return {k: v for k, v in data.items() if v is not None or k in cls.model_fields}


def _code(v: Any) -> Any:
    """Taxonomy codes are lower-case: ' Livelihoods ' is livelihoods, and a blank theme is none."""
    if not isinstance(v, str):
        return v
    return v.strip().lower() or None


class Money(BaseModel):
    """An amount and the unit it was printed in, converted in exactly one place.

    "Rs 1,068.03 crore" read as 1068.03 is the ten-million-fold error, and no
    amount of keyword-sniffing downstream reliably catches it. So the unit is
    not inferred from the text — it is a field, and the source's own wording is
    kept beside it so a person can check.
    """

    model_config = ConfigDict(extra="forbid")

    value: float = Field(ge=0, description="the number as printed, e.g. 1068.03")
    unit: Literal["inr", "lakh", "crore"] = Field(description="the unit that number is in")
    text: str = Field(min_length=1, description="verbatim, e.g. 'Rs 1,068.03 crore'")

    @property
    def inr(self) -> float:
        """The only conversion. Column contract for every amount here is INR.

        Rounded to paise because binary floats cannot hold 4.73 exactly:
        4.73 * 10_000_000 is 47300000.00000001, which is not a rupee amount,
        and made every re-promote look like an edit.
        """
        return round(self.value * _UNITS[self.unit], 2)


def to_inr(money: dict[str, Any] | None) -> float | None:
    """A Money finding in its stored jsonb form, as INR.

    Findings come back out of jsonb as plain dicts, and every caller that
    needed a number was re-deriving the unit table. There is one table.
    """
    if not money or money.get("unit") not in _UNITS:
        return None
    return round(float(money["value"]) * _UNITS[money["unit"]], 2)


class FindingBase(BaseModel):
    """Evidence is not optional. A number with no sentence behind it is not a
    finding, and the length floor is what stops 'see report' standing in for one."""

    model_config = ConfigDict(extra="forbid")

    evidence: str = Field(min_length=20, description="the sentence from the source that states it")
    source_url: str = Field(min_length=1)
    source_name: str | None = None
    confidence: Literal["high", "medium", "low"]
    basis: Literal["explicit", "derived", "inferred"] = "explicit"
    page: str | None = Field(
        default=None, max_length=80,
        description="where in the source: 'p.33', 'pp.33-35', 'Annexure 4', 'CSR page, Programmes tab'",
    )

    _nulls = model_validator(mode="before")(classmethod(_drop_null_extras))

    @field_validator("source_url")
    @classmethod
    def _http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"source_url must be an http(s) URL, got {v!r}")
        return v


_SOURCE_TYPE_HELP = (
    "the KIND of source: registry (a government registry page read directly) · org_document (the "
    "organisation's own document or site) · funder (a funder's page or CSR filing naming it) · "
    "staff_dataset (a staff-uploaded sheet) · prior_research (the team's earlier dossier, not yet re-read "
    "at its source) · aggregator (a third-party NGO directory or listing)"
)
_EVIDENCE_TIER_HELP = (
    "'evidenced' only when the document itself states the fact: a certificate, an audited statement, a "
    "dated return. A sentence on a web page is 'claimed'. aggregator and prior_research are always 'claimed'"
)


class Sourced(BaseModel):
    """What kind of source an organisation's finding came from (C7); the writer ranks on it."""

    source_type: FindingSourceType = Field(description=_SOURCE_TYPE_HELP)
    evidence_tier: EvidenceTier = Field(description=_EVIDENCE_TIER_HELP)

    @model_validator(mode="after")
    def _tier(self) -> Sourced:
        check_tier(self.source_type, self.evidence_tier)
        return self


class OptionallySourced(BaseModel):
    """The same pair on a concept both kinds share: a funder's has none, an organisation's needs both."""

    source_type: FindingSourceType | None = Field(
        default=None, description="REQUIRED for an organisation. " + _SOURCE_TYPE_HELP
    )
    evidence_tier: EvidenceTier | None = Field(
        default=None, description="REQUIRED for an organisation. " + _EVIDENCE_TIER_HELP
    )

    @model_validator(mode="after")
    def _tier(self) -> OptionallySourced:
        check_tier(self.source_type, self.evidence_tier)
        return self


class YearlyFinding(FindingBase):
    fiscal_year: str = Field(description="FY2024-25. Never mix years in one record")

    @field_validator("fiscal_year")
    @classmethod
    def _fy(cls, v: str) -> str:
        if not FISCAL_YEAR.match(v):
            raise ValueError(f"fiscal_year must look like 'FY2023-24', got {v!r}")
        return v


class PlacedFinding(FindingBase):
    """A state is enough to resolve; a district without its state is not."""

    state: str = Field(min_length=2, description="the state as the source names it")
    district: str | None = Field(
        default=None, description="only when the source is that precise; never inferred from a city"
    )


class Tagged(BaseModel):
    """What the work is about, in the taxonomy's own codes: an inference, so it names its evidence."""

    themes: list[str] = Field(
        default_factory=list, max_length=MAX_THEMES, json_schema_extra=_hint(THEME_CODES),
        description="sub-theme codes, or a theme code when only the broad area is clear; at most three, "
                    "the main work first. Only what the source describes, never what the name suggests",
    )
    populations: list[str] = Field(
        default_factory=list, json_schema_extra=_hint(POPULATION_CODES),
        description="who the work is for, only when the source says so",
    )
    lenses: list[str] = Field(
        default_factory=list, json_schema_extra=_hint(LENS_CODES),
        description="cross-cutting approaches the source describes, e.g. digital tools",
    )
    tag_note: str | None = Field(
        default=None,
        description="required with any tag: the words they rest on, e.g. \"programme page: 'SHG federations "
                    "of tribal women in Udalguri'\"",
    )

    @model_validator(mode="after")
    def _tags_name_their_evidence(self) -> Tagged:
        tagged = self.themes or self.populations or self.lenses
        if tagged and not (self.tag_note or "").strip():
            raise ValueError("themes, populations and lenses need a tag_note quoting what they rest on")
        self.themes, self.populations, self.lenses = (
            list(dict.fromkeys(c.strip().lower() for c in v if c.strip()))
            for v in (self.themes, self.populations, self.lenses)
        )
        return self


class IdentityFinding(FindingBase, Tagged):
    concept: Literal["identity"] = "identity"
    name: str = Field(min_length=2, description="the legal name as the strongest source writes it")
    funder_type: (
        Literal["corporate_csr", "corporate_foundation", "private_foundation",
                "family_trust", "family_trust_network", "other"] | None
    ) = None
    section_135_bound: bool | None = Field(default=None, description="null means unknown, not false")
    website: str | None = None
    parent_name: str | None = Field(
        default=None,
        description="the company a foundation belongs to. NEVER merge the two — they are two rows",
    )
    cin: str | None = Field(
        default=None,
        description="the Corporate Identity Number of a COMPANY funder, 21 characters as the MCA prints "
                    "it. A trust or society has none. Never guess one, and never put a parent company's "
                    "CIN on its foundation",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="other names it files or is reported under, e.g. the name on its MCA filings",
    )
    legal_form: str | None = Field(default=None, description="free text as printed, e.g. 'Section 8 Company'")
    founded_year: int | None = Field(
        default=None, ge=1800, le=2100, description="the year it says it was founded or incorporated"
    )
    registered_address: str | None = Field(
        default=None,
        description="the registered office as printed. Its district and state are also a stated_geography "
                    "finding with role 'registered'",
    )
    intake_mode: (
        Literal["open", "rolling", "invitation_only", "rfp_only", "closed", "unknown"] | None
    ) = Field(default=None, description="how an NGO can approach it at all, as it says so")
    funds_external: bool | None = Field(
        default=None, description="what it SAYS about funding other organisations; null means it does not say"
    )
    typical_duration_months: int | None = Field(default=None, gt=0, description="a stated typical grant duration")
    grant_size_min: Money | None = Field(default=None, description="the bottom of a stated grant band")
    grant_size_max: Money | None = Field(default=None, description="the top of a stated grant band")
    as_of: str | None = Field(
        default=None,
        description="when the source says this: a date (2025-04), a year (2025) or a fiscal year (FY2024-25). "
                    "Without it a value that differs from the catalog's waits for a person",
    )

    @field_validator("cin")
    @classmethod
    def _cin(cls, v: str | None) -> str | None:
        if v is None:
            return v
        cin = normalise_cin(v)
        if not CIN_FORMAT.fullmatch(cin):
            raise ValueError(
                f"{v!r} is not a CIN: 21 characters, e.g. 'L65110GJ1993PLC020769'. Never guess one"
            )
        return cin

    @model_validator(mode="after")
    def _band_is_the_right_way_round(self) -> IdentityFinding:
        lo, hi = self.grant_size_min, self.grant_size_max
        if lo is not None and hi is not None and hi.inr < lo.inr:
            raise ValueError(f"grant band is inverted: {lo.text} above {hi.text}")
        return self


class CsrYearFinding(YearlyFinding):
    """One fiscal year of the statutory CSR annexure. Obligation, budget, spend,
    overhead and unspent are separate items and are never interchangeable."""

    concept: Literal["csr_year"] = "csr_year"
    section_135_applicable: bool | None = None
    average_net_profit: Money | None = None
    prescribed_csr: Money | None = Field(default=None, description="item 5(b), the 2% obligation")
    spent_on_projects: Money | None = None
    admin_overheads: Money | None = None
    impact_assessment_cost: Money | None = None
    total_spent: Money | None = Field(default=None, description="item 6(d)")
    unspent_transferred: Money | None = None
    excess_spent: Money | None = None
    local_area_spent: Money | None = Field(
        default=None, description="spent in the local area of its operations, as the MCA return reports it",
    )
    impact_assessment_done: bool | None = None
    notes: str | None = None


class CsrSpendFinding(YearlyFinding):
    """One spend line: a project, or an aggregate. Never divide an aggregate across projects."""

    concept: Literal["csr_spend"] = "csr_spend"
    amount: Money
    outlay: Money | None = Field(
        default=None, description="the amount approved or budgeted for the line, when filed beside the spend"
    )
    project_name: str | None = Field(
        default=None, description="null on an aggregate row; set for a single project"
    )
    project_count: int | None = Field(
        default=None, description="set on an aggregate: how many projects the amount covers"
    )
    state: str | None = None
    district: str | None = None
    sector: str | None = Field(
        default=None, description="the Schedule VII sector the line was FILED under, as printed"
    )
    program_name: str | None = None
    designation: str | None = Field(
        default=None, description="e.g. 'aspirational_district', when the total is limited to those"
    )
    implementation_mode: ImplementationMode | None = None
    partner_name: str | None = Field(default=None, description="the implementing agency or partner, as printed")
    partner_csr1: str | None = Field(default=None, description="the PARTNER's CSR-1, when filed")
    is_ongoing: bool | None = None
    notes: str | None = None
    domain: DomainCode = Field(
        description="ALWAYS set, by project name and partner, not by the filed sector. 'others' for relief, "
                    "sports, administration, unlabelled or multi-sector lines; 'environment' for "
                    "conservation and animal welfare that is not a livelihood programme"
    )
    theme: str | None = Field(
        default=None,
        description="a theme or sub-theme code from the taxonomy, at the most specific level the evidence "
                    "supports; null when the line gives nothing to go on. Never pick one to fill the field",
    )
    classified_by: ClassifiedBy = Field(description="what the domain and theme rest on")
    classification_note: str | None = Field(default=None, description=_NOTE_HELP)

    _codes = field_validator("domain", "theme", mode="before")(lambda v: _code(v))

    @model_validator(mode="after")
    def _aggregate_or_project(self) -> CsrSpendFinding:
        if self.project_name and self.project_count:
            raise ValueError(
                "a row is either one project or an aggregate of several, not both. Drop "
                "project_count, or drop project_name and keep the total"
            )
        _check_classification(self)
        return self


class FootprintFinding(YearlyFinding, PlacedFinding):
    """Where a theme actually ran. The strongest evidence of real geography."""

    concept: Literal["footprint"] = "footprint"
    program_name: str | None = None
    name_as_printed: str | None = Field(
        default=None, description="the place name as the report spelled it"
    )
    notes: str | None = None


class StatedGeographyFinding(PlacedFinding):
    """Where the funder SAYS it prioritises. Not evidence that money went there."""

    concept: Literal["stated_geography"] = "stated_geography"
    role: Literal["registered", "operates", "funds", "priority"] = "priority"
    note: str | None = None


class PartnerFinding(YearlyFinding, OptionallySourced):
    """A named partner and, with an amount, a grant. Keep the year: repeated appearances mean renewal."""

    concept: Literal["partner"] = "partner"
    funder_name: str | None = Field(default=None, description="org research only: who gave the money, as printed")
    partner_name: str = Field(min_length=2, description="as printed in the source")
    partner_canonical: str | None = Field(
        default=None, description="one spelling per partner; count renewals on this"
    )
    partner_kind: (
        Literal["ngo", "foundation", "university", "research", "government",
                "armed_forces", "hospital", "network", "company", "other"] | None
    ) = None
    partner_csr1: str | None = None
    project_name: str | None = Field(
        default=None, description="the grant or project as the source titles it; two projects are two findings"
    )
    start_date: date | None = Field(default=None, description="when the grant or partnership began")
    end_date: date | None = Field(
        default=None,
        description="when it ended or is due to. A multi-year grant is ONE finding with both dates and its "
                    "whole amount, in the fiscal_year it started — never split it across years",
    )
    relationship_status: Literal["active", "concluded", "unconfirmed", "dormant"] | None = Field(
        default=None, description="only when a source says whether it is running; null means not stated"
    )
    outlay: Money | None = Field(
        default=None, description="the amount committed or sanctioned to the partner, when stated beside the grant"
    )
    amount: Money | None = Field(
        default=None,
        description="what the partner received from this funder in the year, or over a multi-year grant, as "
                    "printed with its unit; usually from the recipient's own record. Null means not stated, "
                    "never zero",
    )
    program_name: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _dates_in_order(self) -> PartnerFinding:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError(f"the partnership ends before it starts ({self.start_date} to {self.end_date})")
        if self.start_date and self.fiscal_year != fiscal_year_of(self.start_date):
            raise ValueError(f"a line with a start date sits in the fiscal year it started: "
                             f"{fiscal_year_of(self.start_date)}, not {self.fiscal_year}")
        return self


class ProgrammeSpendFinding(YearlyFinding):
    """The funder's own figure for one programme component in a year (D12). It is the funder's total,
    never a sum of filing lines and never spread across them."""

    concept: Literal["programme_spend"] = "programme_spend"
    program_name: str = Field(min_length=2, description="the programme as the funder names it; also a program finding")
    amount: Money
    domain: DomainCode
    theme: str | None = None
    classified_by: ClassifiedBy = Field(description="usually 'report': the funder's own programme naming")
    classification_note: str | None = Field(default=None, description=_NOTE_HELP)
    notes: str | None = None

    _codes = field_validator("domain", "theme", mode="before")(lambda v: _code(v))

    @model_validator(mode="after")
    def _classified(self) -> ProgrammeSpendFinding:
        _check_classification(self)
        return self


class ProgramFinding(FindingBase, OptionallySourced, Tagged):
    concept: Literal["program"] = "program"
    name: str = Field(min_length=2)
    kind: Literal["theme", "programme", "component", "phase", "project"] = "programme"
    parent_name: str | None = Field(
        default=None, description="the theme or programme above this one, when the source says so"
    )
    description: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_enabler: bool | None = None


class MetricFinding(FindingBase, OptionallySourced):
    concept: Literal["metric"] = "metric"
    name: str = Field(min_length=2)
    value: float | None = None
    target: float | None = None
    unit: str | None = None
    period: str | None = Field(default=None, description="'FY2023-24', or 'cumulative to 2026'")
    stage: (
        Literal["input", "output", "adoption", "outcome",
                "sustained_outcome", "impact", "sroi"] | None
    ) = None
    method: (
        Literal["self_reported", "monitoring_data", "survey", "comparison_study",
                "third_party_evaluation", "estimate"] | None
    ) = None
    is_self_reported: bool = Field(
        default=True, description="never describe a self-reported figure as independently verified"
    )
    baseline: float | None = None
    comparison_value: float | None = None
    chain_key: str | None = Field(default=None, description="rows sharing this form one results chain")
    sequence: int | None = None
    program_name: str | None = None
    state: str | None = None
    district: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _a_metric_needs_a_number(self) -> MetricFinding:
        # The DDL says the same: CHECK (value IS NOT NULL OR target IS NOT NULL).
        if self.value is None and self.target is None:
            raise ValueError(f"metric {self.name!r} has neither a value nor a target")
        return self


class ContactFinding(FindingBase, OptionallySourced):
    """Publicly disclosed CSR roles only. No private personal data."""

    concept: Literal["contact"] = "contact"
    name: str = Field(min_length=2)
    kind: Literal["office_bearer", "programme", "grants", "other"] = "other"
    role: str | None = None
    email: str | None = Field(
        default=None,
        description=(
            "A SHARED mailbox the organisation publishes for enquiries — csr@, grants@, "
            "csrhelpdesk@, contact.us@. Never an individual's address, even a published one. "
            "Set is_role_mailbox and say in the evidence that the page presents it as a "
            "contact point for the organisation."
        ),
    )
    is_role_mailbox: bool = Field(
        default=False,
        description="true only when the address belongs to the organisation, not to a person",
    )
    notes: str | None = None

    @model_validator(mode="after")
    def _only_shared_mailboxes(self) -> ContactFinding:
        # An allowlist of role words would refuse csrhelpdesk@ and
        # youthforindia@, which is most of what a fundraiser wants. Attestation
        # plus one cheap check is more honest than a heuristic that catches
        # r.sharma@ and misses rsharma@.
        if self.email is None:
            return self
        if not self.is_role_mailbox:
            raise ValueError(
                f"{self.email!r} was not attested as a shared mailbox. Sangam records an "
                f"organisation's published contact point, never an individual's address."
            )
        local = self.email.split("@")[0].lower()
        surname = self.name.split()[-1].lower().strip(".")
        if len(surname) > 2 and surname in local.replace(".", "").replace("-", ""):
            raise ValueError(
                f"{self.email!r} contains {surname!r} from the contact's own name, so it "
                f"reads as a personal address rather than a shared one."
            )
        return self


class EligibilityGuidelineFinding(FindingBase):
    """A funder's standing eligibility for applicants, verbatim, from one page (D3).

    Not rfps.eligibility: that is one call's. The same sentence can be true in both places and that
    is two findings, not a duplicate.
    """

    concept: Literal["eligibility_guideline"] = "eligibility_guideline"
    title: str = Field(min_length=4, description="what the page is, e.g. 'CSR Policy — partner selection'")
    as_of: str | None = Field(default=None, description="the period or version the guideline describes")
    statutory_restatement: str | None = Field(
        default=None, description="Rule 4 copied into the policy, VERBATIM. Not the funder's own bar"
    )
    own_bar: str | None = Field(default=None, description="beyond the statutory minimum, verbatim")
    disqualifiers: str | None = Field(default=None, description="stated grounds for rejection, verbatim")
    not_stated: bool = Field(
        default=False, description="true when the page was read and states no eligibility"
    )

    @model_validator(mode="after")
    def _text_or_an_honest_absence(self) -> EligibilityGuidelineFinding:
        texts = [t for t in (self.statutory_restatement, self.own_bar, self.disqualifiers) if t and t.strip()]
        if self.not_stated and texts:
            raise ValueError("not_stated with eligibility text is a contradiction — drop one")
        if not self.not_stated and not texts:
            raise ValueError(
                "no eligibility text: quote the page verbatim, or set not_stated=true if it states none"
            )
        if any(len(t.strip()) < 10 for t in texts):
            raise ValueError("eligibility text is the sentence that states the bar, not a label")
        return self


DocType = Literal[
    "annual_report", "csr_annexure", "brsr", "csr_policy", "csr_impact_report", "impact_assessment",
    "programme_report", "audit_report", "financial_statements", "fcra_return", "registration_certificate",
    "trust_deed", "exemption_order", "exemption_application", "csr1_approval", "fcra_certificate", "policy",
    "press_release", "news_article", "grant_list", "registry_record", "research", "web_page", "other",
]
DOC_TYPES: frozenset[str] = frozenset(get_args(DocType))
# Names research used before the list was fixed, mapped to their kind; anything else unknown is `other`.
DOC_TYPE_ALIASES: dict[str, str] = {
    "csr_report": "csr_impact_report", "csr_action_plan": "csr_annexure",
    "impact_assessment_report": "impact_assessment", "sustainability_report": "brsr",
    "case_study": "programme_report", "program_page": "web_page", "about_page": "web_page",
    "contact_page": "web_page", "grant_guidelines_page": "web_page", "portal": "web_page",
    "news_report": "news_article", "article": "news_article", "ngo_grant_listing": "grant_list",
    "grants_list": "grant_list", "registry": "registry_record", "registry_profile": "registry_record",
    "organisation_profile": "registry_record", "funder_profile": "registry_record",
    "academic_paper": "research", "analysis": "research", "reference": "research", "encyclopedia": "research",
    "subsidiary_financial_statements": "financial_statements",
}


class DocumentFinding(FindingBase):
    concept: Literal["document"] = "document"
    title: str = Field(min_length=2)
    doc_type: DocType = Field(description="the kind of document; a web page is web_page")
    as_of: str | None = Field(
        default=None, description="the period the document describes — not when you read it"
    )
    summary: str | None = Field(
        default=None,
        description="two to four sentences on what the whole document covers: its programmes, years, figures "
                    "and places, not only the line you quoted",
    )

    @field_validator("doc_type", mode="before")
    @classmethod
    def _not_reserved(cls, v: Any) -> Any:
        if v in RESERVED_DOC_TYPES:
            raise ValueError(
                f"doc_type {v!r} is reserved: eligibility is an eligibility_guideline finding, and "
                f"templates and staff datasets have their own paths"
            )
        if isinstance(v, str):
            v = v.strip().lower()
            return v if v in DOC_TYPES else DOC_TYPE_ALIASES.get(v, "other")
        return v


class RfpFinding(FindingBase):
    """An open call for proposals: the thing a fundraiser can actually act on.

    `rfps` has had `deadline`, `amount_min`, `amount_max` and `eligibility`
    since the baseline schema, and no concept pointed at them — so nobody was
    ever asked to look for one.
    """

    concept: Literal["rfp"] = "rfp"
    title: str = Field(min_length=4, description="the call as the funder names it")
    status: Literal["open", "closed", "removed"] = "open"
    url: str | None = Field(default=None, description="where an NGO applies or reads more")
    deadline: date | None = Field(
        default=None, description="the application closing date, when one is published"
    )
    amount_min: Money | None = None
    amount_max: Money | None = None
    eligibility: list[str] = Field(
        default_factory=list,
        description="each stated requirement as its own line, e.g. '3 years of audited accounts'",
    )
    state: str | None = Field(default=None, description="when the call is limited to one state")
    district: str | None = None
    sector: str | None = Field(default=None, description="the theme the call is for, as printed")


# --- The org side -----------------------------------------------------------
# Namespaced because this is a tagged union on `concept`: two members cannot
# both declare Literal["identity"]. Amounts are Money even though the columns
# are numeric — the test compares names, and a bare float is how the crore bug
# gets reintroduced on a new surface.


class OrgIdentityFinding(FindingBase, Sourced, Tagged):
    """An NGO, not a funder."""

    concept: Literal["org_identity"] = "org_identity"
    name: str = Field(min_length=2, description="the legal name as the strongest source writes it")
    org_kind: Literal["cso", "intermediary", "government"] | None = None
    legal_form: str | None = Field(
        default=None, description="free text as printed, e.g. 'Public Charitable Trust'"
    )
    registration_date: date | None = None
    registered_address: str | None = Field(
        default=None,
        description="the registered office as printed. Its district and state are also an org_location finding "
                    "with role 'registered'",
    )
    parent_name: str | None = Field(
        default=None,
        description="the organisation this one belongs to or was spun out of, as printed. Linked only when "
                    "Sangam holds it; never merged with it",
    )
    website: str | None = Field(default=None, description="the organisation's own site")
    description: str | None = Field(default=None, description="a few sentences in its own words")
    aliases: list[str] = Field(
        default_factory=list,
        description="every other spelling a source used: short names, filings, directories. Never another "
                    "organisation's name",
    )
    staff_count: int | None = Field(
        default=None, ge=0, description="as the source states; '20+' is 20, with the wording in staff_count_note"
    )
    staff_count_note: str | None = Field(
        default=None,
        description="what was counted and where, e.g. '20+ full-time professionals (team page)'. A different "
                    "count from another page is its own finding",
    )

    _site = field_validator("website")(lambda v: http_url(v))


class OrgIdentifierFinding(FindingBase, Sourced):
    """One registration and its status. A Form 10AB acknowledgement is 'applied', never 'registered'; a
    registry nobody could read is 'check_blocked', never assumed valid."""

    concept: Literal["org_identifier"] = "org_identifier"
    # An ID card prints only a label and a number, e.g. "PAN Card AAETS7554F".
    evidence: str = Field(min_length=8, description="the line as printed on the document, label included")
    id_type: Literal["pan", "12a", "80g", "fcra", "csr1", "darpan", "cin", "reg_no"]
    id_value: str | None = Field(
        default=None,
        description="exactly as printed. Empty only while it is applied for. Never guess an identifier",
    )
    status: IdentifierStatus = Field(
        description="what the source shows, not what you expect: registered · applied (an acknowledgement, "
                    "put its number in application_ref) · provisional · expired · suspended · cancelled · "
                    "surrendered · not_available · not_found (a working source did not list it) · "
                    "check_blocked (the registry could not be read — never treat it as valid)"
    )
    valid_from: date | None = None
    valid_until: date | None = Field(default=None, description="an approval's end date, when stated")
    check_method: Literal["document", "registry", "aggregator"] | None = Field(
        default=None, description="how the status was read: the CSO's own document, a registry, an aggregator"
    )
    application_ref: str | None = Field(default=None, description="e.g. a Form 10AB acknowledgement number")
    notes: str | None = None

    @model_validator(mode="after")
    def _a_status_has_what_it_needs(self) -> OrgIdentifierFinding:
        check_registration(self.id_value, self.application_ref, self.status, self.evidence_tier)
        return self


class OrgFinancialsFinding(YearlyFinding, Sourced):
    concept: Literal["org_financials"] = "org_financials"
    total_income: Money | None = None
    program_spend: Money | None = Field(
        default=None, description="spent on programmes, not the total. The two are different"
    )
    non_program_spend: Money | None = None
    foreign_contribution: Money | None = Field(
        default=None, description="FCRA receipts for the year, when the return states them"
    )
    foreign_unspent: Money | None = Field(
        default=None, description="foreign contribution unutilised at year end, from the FCRA return"
    )
    is_audited: bool | None = Field(default=None, description="null means unknown, not false")
    notes: str | None = None


class OrgLocationFinding(PlacedFinding, Sourced):
    """Where an NGO works. role='registered' is its registered address."""

    concept: Literal["org_location"] = "org_location"
    role: Literal["registered", "operates", "funds"] = "operates"
    program_name: str | None = Field(
        default=None, description="the organisation's programme that runs here, as the source names it"
    )
    note: str | None = None


Finding = Annotated[
    IdentityFinding | CsrYearFinding | CsrSpendFinding | FootprintFinding
    | StatedGeographyFinding | PartnerFinding | ProgrammeSpendFinding | ProgramFinding | MetricFinding
    | ContactFinding | DocumentFinding | RfpFinding | EligibilityGuidelineFinding
    | OrgIdentityFinding | OrgIdentifierFinding | OrgFinancialsFinding | OrgLocationFinding,
    Field(discriminator="concept"),
]

FINDING_MODELS: dict[str, type[FindingBase]] = {
    "identity": IdentityFinding, "csr_year": CsrYearFinding,
    "csr_spend": CsrSpendFinding, "footprint": FootprintFinding,
    "stated_geography": StatedGeographyFinding, "partner": PartnerFinding,
    "programme_spend": ProgrammeSpendFinding,
    "program": ProgramFinding, "metric": MetricFinding,
    "contact": ContactFinding, "document": DocumentFinding, "rfp": RfpFinding,
    "eligibility_guideline": EligibilityGuidelineFinding,
    "org_identity": OrgIdentityFinding, "org_identifier": OrgIdentifierFinding,
    "org_financials": OrgFinancialsFinding, "org_location": OrgLocationFinding,
}


YEARLY: frozenset[str] = frozenset(c for c, m in FINDING_MODELS.items() if issubclass(m, YearlyFinding))


class Gap(BaseModel):
    """Something looked for and not got; the coverage report reads these."""

    model_config = ConfigDict(extra="forbid")

    concept: str = Field(description="a concept from research_goals, e.g. 'rfp' or 'csr_year'")
    fiscal_year: str | None = Field(
        default=None, description="for a year-bound concept, the year missing; empty means every year asked"
    )
    field: str | None = Field(default=None, description="one field, when the concept was found without it")
    reason: Literal["not_stated", "blocked", "not_reached"] = Field(
        description="'blocked' if the source could not be read (403, JS-only page, a staff file that "
                    "failed or was not selected); 'not_stated' if it was read and does not say; "
                    "'not_reached' if the run stopped before looking (name what was left unread)"
    )
    detail: str = Field(min_length=3, description="one sentence: which source, and what happened")

    @field_validator("concept")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in CONCEPTS:
            raise ValueError(f"unknown concept {v!r}; allowed: {list(CONCEPTS)}")
        return v

    @model_validator(mode="after")
    def _year_only_when_yearly(self) -> Gap:
        if self.fiscal_year and self.concept not in YEARLY:
            raise ValueError(f"{self.concept!r} is not by year; leave fiscal_year empty")
        if self.fiscal_year and not FISCAL_YEAR.match(self.fiscal_year):
            raise ValueError(f"fiscal_year must look like 'FY2023-24', got {self.fiscal_year!r}")
        return self


class Unplaced(BaseModel):
    """A fact a source states that no concept has a field for; the brief shows it, the catalog cannot yet."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=2, description="what it is, e.g. 'registered_address', 'co_funding_share'")
    value: str = Field(min_length=1, description="the value as the source states it")
    evidence: str = Field(min_length=20, description="the sentence from the source that states it")
    source_url: str = Field(min_length=1)
    page: str | None = Field(default=None, max_length=80)

    @field_validator("source_url")
    @classmethod
    def _http(cls, v: str) -> str:
        return FindingBase._http(v)


class EntityResearch(BaseModel):
    """One organisation, researched once."""

    model_config = ConfigDict(extra="forbid")

    entity_name: str = Field(min_length=2, description="the name as it was asked for")
    canonical_name: str | None = Field(default=None, description="as the strongest source writes it")
    entity_kind: Literal["funder", "org", "unknown"] = Field(
        description="'funder' if it GIVES money, 'org' if it RECEIVES it. 'unknown' only when "
                    "the research did not get far enough to tell"
    )
    website: str | None = None
    status: Literal["complete", "partial", "not_found", "wrong_entity"]
    stopped_reason: str | None = Field(
        default=None,
        description="REQUIRED when status is 'partial' or 'wrong_entity': why research ended where it did, "
                    "e.g. 'Stopped at the reading limit. Unread: the FY2024-25 annual report'",
    )
    summary: str = Field(min_length=20, description="a few sentences, factual, no judgement")
    goals: list[str] = Field(
        default_factory=list,
        description="what you set out to find, from research_goals, one line each",
    )
    years: list[str] = Field(
        default_factory=list, description="the fiscal years you were asked to cover, e.g. ['FY2024-25']"
    )
    findings: list[Finding] = Field(default_factory=list)
    gaps: list[Gap] = Field(
        default_factory=list,
        description="every concept, year or field you looked for and did not get, with why. "
                    "Unlisted and unfound reads as 'not attempted'",
    )
    sources_read: list[str] = Field(default_factory=list)
    unplaced: list[Unplaced] = Field(
        default_factory=list,
        description="facts a source states that no concept has a field for: never dropped, never forced into one",
    )

    _nulls = model_validator(mode="before")(classmethod(_drop_null_extras))

    @field_validator("years")
    @classmethod
    def _fiscal_years(cls, v: list[str]) -> list[str]:
        bad = [y for y in v if not FISCAL_YEAR.match(y)]
        if bad:
            raise ValueError(f"years must look like 'FY2023-24', got {bad}")
        return v

    @property
    def not_found(self) -> list[str]:
        """Concepts with no finding and at least one gap; the brief's 'Looked for, not found'."""
        found = set(self.concepts_found())
        return sorted({g.concept for g in self.gaps if g.concept not in found})

    @model_validator(mode="after")
    def _complete_means_something_was_found(self) -> EntityResearch:
        # A field validator would not run here: `findings` defaults to [], and
        # pydantic skips validators on defaults. A "complete" result with
        # nothing in it is a contradiction — the honest shapes are 'not_found',
        # or 'partial' with a reason.
        if self.status == "complete" and not self.findings:
            raise ValueError("status 'complete' with no findings — use 'not_found' or 'partial'")
        if self.status in ("partial", "wrong_entity") and not self.stopped_reason:
            raise ValueError(f"status {self.status!r} needs a stopped_reason saying why")
        # A run that read enough to report findings read enough to say which
        # kind it was reading about — the two sit in the same first search.
        # 'unknown' survives for not_found and wrong_entity, where it is true.
        if self.status in ("complete", "partial") and self.entity_kind == "unknown":
            raise ValueError(
                f"status {self.status!r} with entity_kind 'unknown' — research that got this far "
                f"knows whether the organisation gives money ('funder') or receives it ('org')"
            )
        if self.entity_kind == "org":
            # An org's shared concepts are ranked at promotion, so the tier is required at save.
            tierless = sorted({f.concept for f in self.findings if f.concept in ("program", "metric", "contact", "partner")
                               and (getattr(f, "source_type", None) is None
                                    or getattr(f, "evidence_tier", None) is None)})
            if tierless:
                raise ValueError(f"an org's {tierless} findings need source_type and evidence_tier")
        return self

    @model_validator(mode="after")
    def _gaps_fit_the_kind(self) -> EntityResearch:
        if self.entity_kind == "unknown":
            return self
        wrong = sorted({g.concept for g in self.gaps} - set(concepts_for(self.entity_kind)))
        if wrong:
            raise ValueError(f"gaps name {wrong}, which a {self.entity_kind} is not researched for; "
                             f"allowed: {list(concepts_for(self.entity_kind))}")
        return self

    @model_validator(mode="after")
    def _sources_are_labelled_honestly(self) -> EntityResearch:
        from app.ingest import source_guards  # it reads FINDING_MODELS from here at promote

        wrong = source_guards.check_research(self.findings, self.entity_kind)
        if wrong:
            raise ValueError("; ".join(wrong))
        return self

    def by_concept(self, concept: str) -> list[FindingBase]:
        return [f for f in self.findings if f.concept == concept]

    def concepts_found(self) -> list[str]:
        return sorted({f.concept for f in self.findings})


class ResearchSummary(BaseModel):
    """What a subagent hands back to the parent, and what the Import board reads.

    Deliberately thin. The findings themselves reach the database through
    save_research, so returning them again would make the model emit the whole
    payload twice — and a union this large as a response_format fails hard,
    losing the task, where a tool error comes back and gets corrected.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str
    entity_name: str
    canonical_name: str | None = None
    status: Literal["complete", "partial", "not_found", "wrong_entity"]
    stopped_reason: str | None = None
    # Required for the same reason fact_count is, plus one the parent acts on:
    # it decides whether a catalog-writer is launched at all. An NGO has no
    # writer, so launching one burns a subagent to produce only a refusal.
    entity_kind: Literal["funder", "org", "unknown"]
    # Required, not defaulted: a model that omits it would put "0 facts" on
    # the board next to a researcher that found thirty.
    fact_count: int
    source_count: int = 0
    concepts_found: list[str] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
    saved: bool = Field(default=False, description="true only if save_research returned success")



class WorkbookEntity(BaseModel):
    """One organisation a staff workbook names, and the cell that names it."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Literal["funder", "org", "unknown"]
    marker: str = Field(description="the [source:<document>#<sheet>!<cell>] marker of the cell holding the name")


class VaultResearch(BaseModel):
    """What the vault-reader found in one organisation's own files about one entity."""

    model_config = ConfigDict(extra="forbid")

    entity_name: str = Field(min_length=2, description="the name as it was asked for, exactly")
    entity_kind: Literal["funder", "org"]
    org_id: int = Field(description="the organisation whose Doc Vault was read, from list_vault_documents")
    documents_read: list[int] = Field(description="every vault document id you read")
    findings: list[Finding] = Field(default_factory=list)
    gaps: list[Gap] = Field(
        default_factory=list, description="each concept you looked for in the files and did not find"
    )

    def concepts_found(self) -> list[str]:
        return sorted({f.concept for f in self.findings})


def _known_concepts(values: list[str]) -> list[str]:
    from app.ingest.expectations import CONCEPTS

    unknown = [v for v in values if v not in CONCEPTS]
    if unknown:
        raise ValueError(f"not concept names: {unknown}")
    return values


class VaultSummary(BaseModel):
    """What the vault-reader hands back: ids and concept names only, so no private wording leaves it."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    saved: bool
    concepts_found: list[str]
    concepts_missing: list[str] = Field(description="concepts from research_goals the files do not answer")
    documents_read: list[int]
    fact_count: int

    _concepts = field_validator("concepts_found", "concepts_missing")(_known_concepts)


class WorkbookEntities(BaseModel):
    """What the workbook-reader hands back: names to research, never figures."""

    model_config = ConfigDict(extra="forbid")

    documents: list[int]
    entities: list[WorkbookEntity]
    complete: bool = Field(description="false when some rows were not read; say which in notes")
    notes: list[str] = Field(default_factory=list)

class TableWrite(BaseModel):
    """One catalog table, and how many rows of it a promotion produced."""

    model_config = ConfigDict(extra="forbid")

    table: str
    rows: int


class PromotionReport(BaseModel):
    """What the catalog-writer hands back: what landed, and what did not.

    Deliberately not a place to put facts. Everything here is read back out of
    the database after the write, so the report describes rows that exist
    rather than rows a model believes it created.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str
    entity_name: str | None = None
    entity_id: int | None = None
    entity_kind: Literal["funder", "org"] | None = None
    tables_written: list[TableWrite] = Field(default_factory=list)
    rows_written: int
    held_back: list[str] = Field(
        default_factory=list, description="verbatim reasons, each a decision for a person"
    )
    conflicts: list[str] = Field(
        default_factory=list,
        description="a source that disagrees with a stored value: both values and both sources, verbatim. "
                    "The stored value was kept",
    )
    still_research: list[str] = Field(
        default_factory=list, description="concepts saved under a shape no writer reads"
    )
    verified: bool = Field(
        default=False, description="true only if the dossier was read back and agreed"
    )
