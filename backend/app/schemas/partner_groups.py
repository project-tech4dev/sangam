from pydantic import Field

from app.schemas.common import ReadModel
from app.schemas.partner_lines import PartnerLineOut


class PartnerGroup(ReadModel):
    """One partner of a funder, or one funder of an org, with every public line between them."""

    key: str                          # 'o<org id>' or 'n<folded partner name>' on a funder; the funder id on an org
    name: str
    org_slug: str | None = None       # a partner the Registry lists
    funder_slug: str | None = None
    lines: list[PartnerLineOut] = Field(default_factory=list)


class PartnerGroupPage(ReadModel):
    """A page of groups, newest first; `total` counts every group, not just this page's."""

    groups: list[PartnerGroup] = Field(default_factory=list)
    total: int = 0
    in_registry: int = 0              # partners the Registry lists, across every page
    has_amounts: bool = False
    next_cursor: str | None = None
