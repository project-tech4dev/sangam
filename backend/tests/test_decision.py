"""Step 18 of the change check: one decision per entity."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.ingest.refresh import decision
from app.ingest.refresh.compare import CHANGED, DIFFERS, MINOR, UNCHANGED
from app.ingest.refresh.discover import Discovery
from tests.test_change_check import SLUG
from tests.test_diff_evidence import check
from tests.test_discover import RESULTS, Lead

FOUND = Discovery(new=[(Lead.of(RESULTS[2]), "programme: a fellowship")])


def checks(*statuses: str):
    return [check(status=s) for s in statuses]


@pytest.mark.parametrize(("statuses", "found", "verdict"), [
    ((UNCHANGED, UNCHANGED), Discovery(), decision.NOTHING),
    ((UNCHANGED, MINOR, "unverified"), Discovery(), decision.NOTHING),
    ((UNCHANGED, CHANGED), Discovery(), decision.REFRESH),
    ((UNCHANGED, "dead"), Discovery(), decision.REFRESH),
    ((UNCHANGED, MINOR), FOUND, decision.REFRESH),
])
def test_the_decision_table(statuses, found, verdict):
    assert decision.decide(checks(*statuses), found, redesign=False) == verdict


def test_a_redesign_is_a_full_pull_whatever_else_it_found():
    assert decision.decide(checks(UNCHANGED), FOUND, redesign=True) == decision.FULL_PULL


OLD = "Old home\nOld about\n© 2025"
REBUILT = replace(check(status=DIFFERS, old=OLD), removed=("Old home", "Old about", "© 2025"))
FOOTER = replace(check(status=DIFFERS, old=OLD), removed=("© 2025",))


@pytest.mark.parametrize(("sources", "redesign"), [
    ([REBUILT] * 3 + checks(UNCHANGED), True),
    ([REBUILT] * 2 + checks(UNCHANGED, UNCHANGED), False),  # exactly half is not more than half
    ([REBUILT] + checks("unverified", "unverified", "unverified"), False),  # a failed fetch is not a change
    ([FOOTER] * 4, False),  # 1 January: every page differs by one line
    (checks(MINOR, MINOR, MINOR, UNCHANGED), False),
    ([], False),
], ids=["most-rebuilt", "half", "unverified", "new-footer-year", "minor", "none"])
def test_more_than_half_rebuilt_is_a_redesign(sources, redesign):
    assert decision.redesigned(sources) is redesign


@pytest.mark.parametrize("count", [1, 2, 3])
def test_a_funder_with_few_sources_is_never_a_redesign(count):
    """One page edit on a one-page funder is a refresh, not a full pull."""
    assert not decision.redesigned([REBUILT] * count)


def test_settle_takes_what_still_differs_as_changed():
    settled = decision.settle([replace(check(status=DIFFERS), reason="3 removed"), check(status=MINOR)])
    assert [c.status for c in settled] == [CHANGED, MINOR]
    assert settled[0].reason == f"3 removed; {decision.REDESIGN_REASON}"


def test_describe():
    line = decision.describe(SLUG, checks(UNCHANGED, UNCHANGED, CHANGED), FOUND, decision.REFRESH)
    assert line == f"{SLUG}: 3 sources · 1 changed · 2 unchanged · 1 new → refresh"
    assert decision.describe(SLUG, checks(UNCHANGED), Discovery(), decision.NOTHING).endswith("unchanged → nothing to do")


def gap_found(read: bool) -> Discovery:
    lead = Lead.of(RESULTS[2])
    return Discovery(gap_leads=[(lead, "csr_year", "a filing")], fetched={lead.url: object()} if read else {})


@pytest.mark.parametrize(("read", "verdict"), [(True, decision.REFRESH), (False, decision.NOTHING)])
def test_a_gap_source_alone_refreshes_only_once_it_was_read(read, verdict):
    assert decision.decide(checks(UNCHANGED), gap_found(read), redesign=False) == verdict


def test_describe_counts_gap_sources():
    line = decision.describe(SLUG, checks(UNCHANGED), gap_found(True), decision.REFRESH)
    assert line == f"{SLUG}: 1 sources · 1 unchanged · 1 for gaps → refresh"
