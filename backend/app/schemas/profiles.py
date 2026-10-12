from __future__ import annotations

from app.schemas.common import Page, ReadModel
from app.schemas.documents import FileLinkOut
from app.schemas.funders import FunderDetail
from app.schemas.news_stories import StoryOut
from app.schemas.orgs import OrgDetail
from app.schemas.partner_lines import PartnerLineOut
from app.schemas.programs import ProgramOut
from app.schemas.scores import FitScoreOut


class OrgProfile(ReadModel):
    """Everything an organisation's profile page shows, in one response."""

    org: OrgDetail
    funding: list[PartnerLineOut]
    programs: list[ProgramOut]
    scores: list[FitScoreOut]
    news: list[StoryOut]


class FunderProfile(ReadModel):
    """Everything a funder's profile page shows, in one response."""

    funder: FunderDetail
    scores: list[FitScoreOut]
    partners: Page[PartnerLineOut]
    news: list[StoryOut]
    brief: FileLinkOut | None = None
