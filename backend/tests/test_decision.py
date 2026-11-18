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


@pytest.mark.parametrize(("statuses", "redesign"), [
    ((DIFFERS, DIFFERS, UNCHANGED), True),
    ((DIFFERS, UNCHANGED), False),  # exactly half is not more than half
    ((DIFFERS, "unverified", "unverified"), False),  # a failed fetch is not a change
    ((), False),
])
def test_more_than_half_differing_is_a_redesign(statuses, redesign):
    assert decision.redesigned(checks(*statuses)) is redesign


def test_settle_takes_what_still_differs_as_changed():
    settled = decision.settle([replace(check(status=DIFFERS), reason="3 removed"), check(status=MINOR)])
    assert [c.status for c in settled] == [CHANGED, MINOR]
    assert settled[0].reason == f"3 removed; {decision.REDESIGN_REASON}"


def test_describe():
    line = decision.describe(SLUG, checks(UNCHANGED, UNCHANGED, CHANGED), FOUND, decision.REFRESH)
    assert line == f"{SLUG}: 3 sources · 1 changed · 2 unchanged · 1 new → refresh"
    assert decision.describe(SLUG, checks(UNCHANGED), Discovery(), decision.NOTHING).endswith("unchanged → nothing to do")
