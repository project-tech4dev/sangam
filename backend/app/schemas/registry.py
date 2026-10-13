from datetime import date

from pydantic import Field

from app.schemas.common import ReadModel


class RegistryTheme(ReadModel):
    label: str
    domain: str | None = None         # the top of the theme tree, which the Theme filter offers


class RegistryRow(ReadModel):
    """One CSO or funder as the Registry list shows it, with what its filters and search read."""

    kind: str                         # 'org' | 'funder'
    id: int
    slug: str
    name: str
    funder_type: str | None = None
    place: str | None = None          # an org's leading district and state, "Udalguri, Assam"
    states: list[str] = Field(default_factory=list)
    themes: list[RegistryTheme] = Field(default_factory=list)
    lenses: list[str] = Field(default_factory=list)
    sdgs: list[str] = Field(default_factory=list)
    csr1: bool = False                # org registrations on file (registered or provisional, current)
    has_12a_80g: bool = False
    fcra: bool = False
    intake_mode: str | None = None
    open_call: bool = False
    partners: int = 0                 # public partner lines (a funder) or funders named (an org)
    csr_prescribed: float | None = None
    csr_year: str | None = None
    press: int = 0                    # public stories, counted in SQL as the profile counts them
    social: int = 0
    posts_since: date | None = None
    research_runs: int = 0
    researched_on: date | None = None
    search: str = ""                  # aliases, districts, programmes and partner names, lower-cased


class RegistryOut(ReadModel):
    rows: list[RegistryRow]
