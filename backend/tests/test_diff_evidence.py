"""Steps 13 and 14 of the change check: what text changed, and whether each fact's sentence survived."""

from __future__ import annotations

from datetime import date

import pytest

from app.ingest.refresh import diff, evidence
from app.ingest.refresh.baseline import Baseline
from app.ingest.refresh.compare import CHANGED, DIFFERS, MINOR, UNCHANGED, Check
from app.ingest.refresh.evidence import BROKEN, INTACT, UNANCHORED
from app.ingest.refresh.fetch_status import OK, Today
from tests.cov_ingest_fakes import ScriptConn

URL = "https://funder.example/about"
OLD = "The Foundation supports over 400 organisations.\n\nWe work in Karnataka and Uttarakhand.\n© 2025"
NEW = "We work in Karnataka and Uttarakhand.\n\nThe Foundation supports over 500 organisations.\n© 2025"


def check(new: str = NEW, key: str | None = "3fa9/abc-about.md", kind: str = "page", status: str = DIFFERS,
          old: str | None = None) -> Check:
    return Check(Baseline(URL, 7, kind, "a" * 64, key, 31, date(2026, 11, 14)),
                 Today(URL, OK, "HTTP 200", text=new, fingerprint="b" * 64), status, old_text=old)


async def _value(v):
    return v


class TestDiff:
    def test_paragraphs_are_normalised_and_blanks_dropped(self):
        assert diff.paragraphs("  a\u200b  b \n\n\nc\n") == ["a b", "c"]

    def test_a_changed_sentence_is_one_out_one_in(self):
        removed, added = diff.diff(OLD, NEW)
        assert removed == ("The Foundation supports over 400 organisations.",)
        assert added == ("The Foundation supports over 500 organisations.",)

    def test_a_moved_paragraph_is_not_a_change(self):
        assert diff.diff("a\nb\nc", "c\na\nb") == ((), ())

    def test_a_repeated_paragraph_counts(self):
        assert diff.diff("a\na\nb", "a\nb") == (("a",), ())


class TestOldText:
    async def test_no_archive_key_is_none(self):
        assert await diff.old_text(check(key=None).baseline) is None

    async def test_a_failed_read_is_none(self, monkeypatch):
        monkeypatch.setattr(diff.storage, "download", lambda bucket, key: _value(None))
        assert await diff.old_text(check().baseline) is None

    async def test_a_page_is_its_archived_text(self, monkeypatch):
        monkeypatch.setattr(diff.storage, "download", lambda bucket, key: _value(OLD.encode()))
        assert await diff.old_text(check().baseline) == OLD

    async def test_a_document_is_its_extracted_text(self, monkeypatch):
        monkeypatch.setattr(diff.storage, "download", lambda bucket, key: _value(b"%PDF-1.4"))
        monkeypatch.setattr(diff, "document_text", lambda path: f"text of {path.name}")
        source = check(key=f"77c2d0e4b1aa/{'5' * 64}-annual.pdf", kind="document").baseline
        assert await diff.old_text(source) == "text of annual.pdf"


class TestRun:
    @pytest.fixture
    def archive(self, monkeypatch):
        state = {"old": OLD}

        async def old_text(source):
            return state["old"]
        monkeypatch.setattr(diff, "old_text", old_text)
        return state

    async def test_a_real_change_keeps_the_diff(self, archive):
        [c] = await diff.run([check()])
        assert c.status == DIFFERS and c.old_text == OLD and len(c.removed) == len(c.added) == 1

    async def test_no_archive_is_assumed_changed(self, archive):
        archive["old"] = None
        assert (await diff.run([check()]))[0].status == CHANGED

    async def test_only_reordered_is_minor(self, archive):
        archive["old"] = "b\na"
        assert (await diff.run([check(new="a\nb")]))[0].status == MINOR

    async def test_a_scan_with_no_text_either_side_is_changed(self, archive):
        archive["old"] = ""
        assert (await diff.run([check(new="", kind="document")]))[0].status == CHANGED

    async def test_other_sources_are_left_alone(self, archive):
        same = check(status=UNCHANGED)
        assert await diff.run([same]) == [same]

    def test_describe_shows_both_sides_and_counts_the_rest(self):
        many = check(old=OLD)
        many = Check(many.baseline, many.today, DIFFERS, "x", OLD, removed=("gone",),
                     added=tuple(f"new {i}" for i in range(10)))
        out = diff.describe("zz", [many, check(status=UNCHANGED)])
        assert "      - gone" in out and "      + new 7" in out and "      + … and 2 more" in out
        assert out.count(URL) == 1


class TestEvidence:
    def test_a_moved_sentence_is_intact(self):
        assert evidence.verdict("We work in Karnataka and Uttarakhand.", OLD, NEW) == INTACT

    def test_a_changed_number_is_broken(self):
        assert evidence.verdict("The Foundation supports over 400 organisations.", OLD, NEW) == BROKEN

    @pytest.mark.parametrize("old, new", [
        ("Applications for the 2025 grant cycle are open until 31 March 2025 for registered NGOs.",
         "Applications for the 2025 grant cycle are open until 31 May 2025 for registered NGOs."),
        ("Applications for the 2025 grant cycle are open until 31 March 2025 for registered NGOs.",
         "Applications for the 2025 grant cycle are closed until 31 March 2025 for registered NGOs."),
        ("The Foundation funds registered NGOs working in Assam and Meghalaya on livelihoods.",
         "The Foundation does not fund registered NGOs working in Assam and Meghalaya on livelihoods."),
    ])
    def test_a_changed_word_is_broken_though_the_numbers_match(self, old, new):
        assert evidence.verdict(old, old, new) == BROKEN

    def test_a_page_holding_only_a_fragment_of_the_sentence_is_broken(self):
        sentence = "Applications for the 2025 grant cycle are open until 31 March 2025 for registered NGOs."
        assert evidence.verdict(sentence, sentence, "open until 31 March 2025") == BROKEN

    def test_a_page_break_inside_the_sentence_is_not_a_change(self):
        sentence = "The Foundation supported 412 organisations across Assam and Meghalaya in 2024."
        old = f"--- page 5 ---\nIntro.\n{sentence}\nMore."
        new = ("--- page 5 ---\nIntro.\nThe Foundation supported 412 organisations across\n\n"
               "--- page 6 ---\nAssam and Meghalaya in 2024.\nMore.")
        assert evidence.verdict(sentence, old, new) == INTACT

    def test_a_word_split_by_a_line_end_hyphen_is_not_a_change(self):
        sentence = "The Foundation supported 412 organisations across Assam and Meghalaya in 2024."
        new = "The Foundation supported 412 organi-\nsations across Assam and Meghalaya in 2024."
        assert evidence.verdict(sentence, sentence, new) == INTACT

    def test_a_re_spaced_sentence_with_other_case_is_intact(self):
        sentence = "We work in Karnataka and Uttarakhand."
        assert evidence.verdict(sentence, sentence, "Intro.  WE work   in Karnataka and Uttarakhand.  More.") == INTACT

    def test_a_paraphrase_is_unanchored(self):
        assert evidence.verdict("Hundreds of NGOs receive its grants every year.", OLD, NEW) == UNANCHORED

    def test_a_broken_fact_makes_the_source_changed(self):
        [c] = evidence.run([check(old=OLD)], {URL: ["The Foundation supports over 400 organisations.",
                                                    "We work in Karnataka and Uttarakhand."]})
        assert c.status == CHANGED and "1 intact, 1 broken, 0 unanchored" in c.reason

    def test_all_intact_still_needs_the_judge(self):
        [c] = evidence.run([check(old=OLD)], {URL: ["We work in Karnataka and Uttarakhand."]})
        assert c.status == DIFFERS and c.verdicts == ((INTACT, "We work in Karnataka and Uttarakhand."),)

    def test_a_page_no_fact_cites_says_so(self):
        [c] = evidence.run([check(old=OLD)], {})
        assert c.status == DIFFERS and "no facts cite this page" in c.reason

    def test_without_the_old_text_it_is_skipped(self):
        assert evidence.run([check()], {URL: ["x" * 30]}) == [check()]

    def test_describe_lists_the_broken_sentence(self):
        checks = evidence.run([check(old=OLD)], {URL: ["The Foundation supports over 400 organisations."]})
        assert "      broken: The Foundation supports over 400 organisations." in evidence.describe("zz", checks)

    async def test_findings_are_grouped_by_canonical_url_once_each(self):
        conn = ScriptConn([("FROM entity_research", [
            {"findings": [{"source_url": "https://Funder.example/about", "evidence": "A sentence long enough."},
                          {"source_url": URL, "evidence": "A sentence long enough."},
                          {"source_url": URL, "evidence": ""}]},
            {"findings": None}])])
        assert await evidence.load_findings(conn, "zz") == {URL: ["A sentence long enough."]}
        assert "status <> 'wrong_entity'" in conn.calls[0][0]


class TestNumbers:
    @pytest.mark.parametrize("old, new", [
        ("Grants of Rs 4.5 crore in FY2023-24.", "Grants of Rs 4.8 crore in FY2023-24."),
        ("It reached 12,400 students.", "It reached 12,900 students."),
        ("Founded in 2001, it works in 6 states.", "Founded in 2001, it works in 8 states."),
    ])
    def test_a_changed_figure_is_broken_however_small(self, old, new):
        assert evidence.verdict(old, f"Intro.\n{old}\nMore.", f"Intro.\n{new}\nMore.") == BROKEN

    def test_the_same_figures_elsewhere_on_the_page_do_not_count(self):
        old_page = "It reached 12,400 students.\nOther news."
        new_page = "It reached 12,900 students.\nIn 12,400 homes we saw change."
        assert evidence.verdict("It reached 12,400 students.", old_page, new_page) == BROKEN

    def test_a_number_at_the_end_of_the_sentence_is_still_seen(self):
        page = "Our annual report for 2024"
        assert evidence.on_page("annual report for 2024", page)
