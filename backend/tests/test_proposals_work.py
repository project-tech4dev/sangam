"""work.apply, the one way a proposal changes: allowed paths only, a stale section refused, every change logged."""

from datetime import UTC, datetime

import pytest

from app.proposals import work as rules

RAVI = {"id": "u-ravi", "name": "Ravi"}
ASHA = {"id": "u-asha", "name": "Asha"}
NOON = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _work(**extra):
    return {
        "stage": 1,
        "requirements": [{"key": "12a", "label": "12A registration", "hard": False},
                         {"key": "csr1", "label": "CSR Form 1", "hard": True}],
        "gates": {},
        "earlier_phase": False,
        "sections": {},
        "facts": {"k1": {"status": "proposed", "value": "120 villages"}},
        "log": [],
        **extra,
    }


@pytest.mark.parametrize("path, value", [
    ("summary", {}),
    ("log", []),
    ("work", {}),
    ("gates.g9", "yes"),
    ("gates.12a", "maybe"),
    ("sections.Z9.text", "x"),
    ("sections.A3.score", 2),
    ("facts.k9.status", "confirmed"),
    ("facts.k1.status", "true"),
    ("stage", 2),
    ("sources", ["41"]),
    ("title", "  "),
    ("template.outline", {"headings": []}),
    ("template", {"document_id": 40, "outline": {"headings": []}}),
])
def test_a_path_outside_the_allowed_shapes_is_refused(path, value):
    with pytest.raises(rules.BadChange):
        rules.apply(_work(), {path: value}, {"Z9": 0, "A3": 0}, by=RAVI)


def test_nothing_is_changed_when_one_change_of_several_is_refused():
    work = _work()
    with pytest.raises(rules.BadChange):
        rules.apply(work, {"gates.12a": "yes", "summary": {}}, by=RAVI)
    assert work["gates"] == {} and work["log"] == []


def test_a_section_change_needs_the_rev_it_was_read_at():
    with pytest.raises(rules.BadChange):
        rules.apply(_work(), {"sections.A3.text": "draft"}, by=RAVI)


def test_a_stale_section_is_refused_with_what_is_there_and_who_changed_it():
    first = rules.apply(_work(), {"sections.A3.text": "Ravi's draft"}, {"A3": 0}, by=RAVI, now=NOON).work
    with pytest.raises(rules.StaleSection) as refused:
        rules.apply(first, {"sections.A3.text": "Asha's draft"}, {"A3": 0}, by=ASHA)
    assert refused.value.code == "A3"
    assert refused.value.current["text"] == "Ravi's draft"
    assert refused.value.changed_by == {"by": RAVI, "at": NOON.isoformat()}


def test_a_section_rev_goes_up_once_per_save_and_other_sections_do_not_clash():
    work = rules.apply(_work(), {"sections.A3.text": "a", "sections.A3.done": True}, {"A3": 0}, by=RAVI).work
    assert work["sections"]["A3"]["rev"] == 1
    work = rules.apply(work, {"sections.A2.text": "b"}, {"A2": 0}, by=ASHA).work
    assert work["sections"]["A3"]["rev"] == 1 and work["sections"]["A2"]["rev"] == 1


def test_every_change_is_logged_with_who_how_and_the_values():
    applied = rules.apply(_work(), {"gates.12a": "yes", "facts.k1.status": "confirmed"}, by=RAVI, via="agent",
                          run_id="run-1", reason="the person confirmed it", facts=["k1"], now=NOON)
    assert applied.work["log"] == [
        {"at": NOON.isoformat(), "by": RAVI, "via": "agent", "run_id": "run-1", "path": "gates.12a",
         "from": None, "to": "yes", "facts": ["k1"], "reason": "the person confirmed it"},
        {"at": NOON.isoformat(), "by": RAVI, "via": "agent", "run_id": "run-1", "path": "facts.k1.status",
         "from": "proposed", "to": "confirmed", "facts": ["k1"], "reason": "the person confirmed it"},
    ]


def test_a_long_value_is_cut_in_the_log_and_kept_whole_in_the_section():
    text = "x" * 500
    work = rules.apply(_work(), {"sections.A3.text": text}, {"A3": 0}, by=RAVI).work
    assert work["sections"]["A3"]["text"] == text
    assert len(work["log"][0]["to"]) == rules.LOG_TEXT + 1


def test_a_rename_is_logged_and_returned_as_the_new_title():
    applied = rules.apply(_work(), {"title": " SeSTA → ABF "}, by=RAVI, title="Old name")
    assert applied.title == "SeSTA → ABF"
    assert (applied.work["log"][0]["from"], applied.work["log"][0]["to"]) == ("Old name", "SeSTA → ABF")


def test_a_step_goes_back_by_patch_and_forward_only_by_advance():
    later = _work(stage=3)
    assert rules.apply(later, {"stage": 1}, by=RAVI).work["stage"] == 1
    with pytest.raises(rules.BadChange):
        rules.apply(_work(stage=1), {"stage": 3}, by=RAVI, advance=True)
    assert rules.apply(_work(stage=1), {"stage": 2}, by=RAVI, advance=True).work["stage"] == 2


def test_the_summary_is_recomputed_from_the_new_work():
    applied = rules.apply(_work(), {"gates.12a": "yes", "gates.csr1": "no"}, by=RAVI)
    assert applied.summary["gates_answered"] == 2
    assert "CSR Form 1: the funder needs it" in applied.summary["fix_first"]


def test_only_saving_a_version_keeps_the_forms_outline():
    applied = rules.apply(_work(template={"document_id": 40}), {"template.outline": {"headings": []}},
                          by=RAVI, via="version")
    assert applied.work["template"] == {"document_id": 40, "outline": {"headings": []}}
