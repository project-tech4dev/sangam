"""make news-pull: a slug that matches nothing is refused, and everyone needs an explicit yes."""

from app.ingest.news import run


def test_slugs_that_match_nothing_are_refused():
    assert "matches no" in run.refusal(chosen=True, org_ids=[], funder_ids=[], yes=True)


def test_everyone_needs_an_explicit_yes():
    assert "CONFIRM=1" in run.refusal(chosen=False, org_ids=None, funder_ids=None, yes=False)
    assert run.refusal(chosen=False, org_ids=None, funder_ids=None, yes=True) is None


def test_a_resolved_choice_runs():
    assert run.refusal(chosen=True, org_ids=[4], funder_ids=[], yes=False) is None
