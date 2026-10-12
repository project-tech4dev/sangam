"""Who is searched, with which queries, over which window, and what a run will cost."""

from datetime import date

from app.core.config import Settings
from app.ingest.news import feeds, windows
from app.ingest.news.feeds import Subject

TODAY = date(2026, 10, 11)


def org(name, **kw):
    return Subject(kind="org", id=1, key=name.lower(), name=name, **kw)


class TestQueries:
    def test_a_long_name_is_searched_quoted_with_its_aliases(self):
        s = org("Better Life Foundation", aliases=("BLF Nagaland",))
        assert feeds.queries_for(s) == ['"Better Life Foundation"', '"BLF Nagaland"']

    def test_a_short_or_one_word_name_gets_its_place(self):
        assert feeds.queries_for(org("KABIL", place="Udalguri")) == ['"KABIL"', '"KABIL" Udalguri']

    def test_quotes_in_a_name_do_not_break_the_query(self):
        q = feeds.queries_for(org('People\'s Endeavour for "Social" Changes'))
        assert q[0] == '"People\'s Endeavour for Social Changes"' and '"PESCH"' in q  # PESCH from the namesake file

    def test_the_place_is_the_district_alone_in_title_case(self):
        assert feeds.queries_for(org("KABIL", place="UDALGURI, Assam")) == ['"KABIL"', '"KABIL" Udalguri']

    def test_a_long_name_in_capitals_is_not_ambiguous(self):
        assert feeds.queries_for(org("PEOPLES RESOURCE DEVELOPMENT ASSOCIATION", place="BISHNUPUR, Manipur")) == [
            '"PEOPLES RESOURCE DEVELOPMENT ASSOCIATION"']

    def test_a_bracketed_acronym_is_left_out_of_the_quoted_name(self):
        assert feeds.queries_for(org("Bodoland Development Foundation (BDF)")) == ['"Bodoland Development Foundation"']

    def test_the_namesake_files_spellings_are_searched_too(self):
        q = feeds.queries_for(org("The Action Northeast Trust", place="CHIRANG, Assam"))
        assert '"The ANT"' in q and q[0] == '"The Action Northeast Trust"'

    def test_at_most_four_queries(self):
        s = org("SATRA", aliases=("A", "B", "C", "D"), place="Darrang")
        assert len(feeds.queries_for(s)) == 4

    def test_a_feed_uses_its_own_queries_and_two_scopes(self):
        f = Subject(kind="feed", id=None, key="fcra", name="FCRA")
        assert feeds.queries_for(f) == list(feeds.FEEDS["fcra"].queries)
        assert [name for name, _ in feeds.scopes_for(f)] == ["open_web", "allowlist"]

    def test_the_namesake_note_reaches_the_profile(self):
        assert "Khanij Bidesh" in feeds.profile_for(org("KABIL", place="Udalguri"))


class TestWindows:
    def test_a_newcomer_goes_back_ninety_days(self):
        assert windows.window_days(None, TODAY) == 90

    def test_otherwise_from_the_watermark_with_a_day_of_overlap(self):
        assert windows.window_days(date(2026, 10, 4), TODAY) == 8
        assert windows.window_days(TODAY, TODAY) == 1

    def test_the_plan_counts_searches_newcomers_and_cost(self):
        subs = [org("Better Life Foundation"), org("KABIL", place="Udalguri", searched_through=date(2026, 9, 1))]
        p = windows.plan(subs, today=TODAY, settings=Settings(_env_file=None))
        assert (p.subjects, p.newcomers) == (2, 1)
        assert p.searches == (1 + 2) * 2
        s = Settings(_env_file=None)
        assert p.cost_usd == round(6 * s.news_search_cost_usd + 6 * s.news_links_per_search * s.news_classify_cost_usd, 2)


class TestStaleFloor:
    def test_a_newcomer_keeps_ninety_days(self):
        assert windows.stale_floor(None, TODAY) == date(2026, 7, 13)

    def test_a_late_indexed_item_survives_a_short_window(self):
        # Searched yesterday, but an item published three weeks ago and only now indexed still counts.
        assert windows.stale_floor(date(2026, 10, 10), TODAY) == date(2026, 9, 10)
