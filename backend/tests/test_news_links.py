"""Links: hosts, source types, dates in post IDs, weak titles. Bars: what is listed and what is public."""

from datetime import UTC, date, datetime

import pytest

from app.ingest.news import links
from app.ingest.news.bars import Bars, level, topic_visibility, visibility

BARS = Bars(0.6, 0.8, 0.7, 0.9, 0.9, 0.95)


def _x_status_for(day: date) -> int:
    ms = int(datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp() * 1000)
    return (ms - 1288834974657) << 22


def _linkedin_for(day: date) -> int:
    ms = int(datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp() * 1000)
    return ms << 22


class TestLinks:
    def test_host_drops_www_and_mobile(self):
        assert links.host("https://www.m.eastmojo.com/x") == "eastmojo.com"

    @pytest.mark.parametrize("url, kind, expected", [
        ("https://www.linkedin.com/posts/x-activity-1", None, "LinkedIn"),
        ("https://instagram.com/p/abc", None, "Instagram"),
        ("https://x.com/a/status/1", None, "X"),
        ("https://assamtribune.com/a", "news", "print media"),
        ("https://thecsrjournal.in/a", "news", "CSR or sector media"),
        ("https://example.org/a", "news", "online news"),
        ("https://example.org/a", "press_release", "organisation site"),
        ("https://example.org/a", None, "other web"),
    ])
    def test_source_type(self, url, kind, expected):
        assert links.source_type(url, kind) == expected

    @pytest.mark.parametrize("url, profile", [
        ("https://in.linkedin.com/in/rupam-kalita-0037153b1", True),
        ("https://www.linkedin.com/company/kabil-india/", True),
        ("https://x.com/ajagar_sc/with_replies?lang=bn", True),
        ("https://x.com/ajagar_sc", True),
        ("https://www.instagram.com/akkarafoundation?hl=en", True),
        ("https://www.youtube.com/@tatatrusts", True),
        ("https://www.linkedin.com/posts/kabil_activity-7380000000000000000-abcd", False),
        ("https://www.linkedin.com/company/kabil-india/posts/?feedView=all", True),  # a feed, not one post
        ("https://www.linkedin.com/pulse/csr-in-assam-someone", False),
        ("https://x.com/ajagar_sc/status/1840000000000000000", False),
        ("https://www.instagram.com/p/DPaBcDeFgHi/", False),
        ("https://www.instagram.com/kabil/reel/DPaBcDeFgHi/", False),
        ("https://www.youtube.com/shorts/4rmbAEP6sEU", False),
        ("https://eastmojo.com/assam/2026/10/01/story", False),
        ("https://www.ambitionbox.com/overview/sbi-foundation-overview", True),
        ("https://www.glassdoor.co.in/Overview/Working-at-SBI-Foundation-EI_IE123.htm", True),
        ("https://www.zaubacorp.com/company/KABIL/U00000", True),
        # Job ads: a job board, or a jobs or careers page on any site.
        ("https://www.jobaaj.com/job/azim-premji-foundation-finance-bhopal-536300", True),
        ("https://www.foundit.in/job/programme-officer-sbi-foundation-123", True),
        ("https://internshala.com/internship/detail/csr-intern-at-kabil", True),
        ("https://azimpremjiuniversity.edu.in/careers/finance-officer", True),
        ("https://www.tatatrusts.org/jobs/programme-manager", True),
        ("https://www.linkedin.com/jobs/view/4012345678", True),
        ("https://morungexpress.com/nagaland-must-leverage-agriculture-potential-to-create-jobs-cm-rio", False),
        ("https://www.thehindu.com/news/national/recruitment-drive-for-teachers/article123.ece", False),
    ])
    def test_profile_pages_are_recognised(self, url, profile):
        assert links.is_profile_page(url) is profile

    def test_facebook_is_recognised_so_it_can_be_dropped(self):
        assert links.is_facebook("https://m.facebook.com/story.php?id=1")

    def test_dates_in_post_ids(self):
        day = date(2026, 9, 20)
        assert links.post_id_date(f"https://x.com/someone/status/{_x_status_for(day)}") == day
        url = f"https://www.linkedin.com/posts/org_activity-{_linkedin_for(day)}-abcd"
        assert links.post_id_date(url) == day
        assert links.post_id_date("https://eastmojo.com/2026/09/20/story") is None

    @pytest.mark.parametrize("title, weak", [
        ("Instagram", True), ("#womenempowerment #assam", True), (None, True), ("IMG_2041.jpg", True),
        ("KABIL trains 200 women weavers in Udalguri", False),
        ("#kabil #livelihoods #fisheries #capacitybuilding #udalguri #assam | KABIL", True),
        ("#casestudy #agriculture #sri #kabil #udalguridistrict #krishi… | KABIL", True),
        ("KABIL INDIA | 💧 Empowering Farmers through Access to Irrigation", False),
    ])
    def test_weak_titles(self, title, weak):
        assert links.weak_title(title, "https://instagram.com/p/x") is weak

    def test_keys_ignore_scheme_case_and_punctuation(self):
        assert links.url_key("https://WWW.Site.com/a/") == links.url_key("http://site.com/a")
        assert links.title_key("FCRA: rules, tightened!") == links.title_key("fcra rules tightened")


class TestBars:
    def test_public_needs_news_and_the_high_bar(self):
        assert visibility(0.75, 0.92, sentiment="positive", is_news=True, bars=BARS) == "public"
        assert visibility(0.75, 0.92, sentiment="positive", is_news=False, bars=BARS) == "listed"

    def test_a_negative_story_needs_the_highest_bar(self):
        assert visibility(0.85, 0.94, sentiment="negative", is_news=True, bars=BARS) == "listed"
        assert visibility(0.92, 0.96, sentiment="negative", is_news=True, bars=BARS) == "public"

    def test_below_the_listing_bar_is_hidden(self):
        assert visibility(0.59, 0.99, sentiment="neutral", is_news=True, bars=BARS) == "hidden"
        assert visibility(0.9, 0.79, sentiment="neutral", is_news=True, bars=BARS) == "hidden"

    def test_an_undated_background_item_is_never_listed(self):
        assert visibility(0.95, 0.95, sentiment="neutral", is_news=False, bars=BARS, dated=False) == "hidden"
        assert visibility(0.95, 0.95, sentiment="neutral", is_news=False, bars=BARS, dated=True) == "listed"

    @pytest.mark.parametrize("is_news, dated, scope, expected", [
        (True, True, "north_east", "listed"), (False, True, "national", "hidden"),
        (True, False, "national", "hidden"), (True, True, "international", "hidden"),
    ])
    def test_a_topic_story_is_listed_only_when_it_is_dated_news_about_india(self, is_news, dated, scope, expected):
        assert topic_visibility(0.9, 0.9, is_news=is_news, dated=dated, scope=scope, bars=BARS) == expected

    def test_a_topic_story_needs_the_higher_topic_bar(self):
        """Hedged 0.6-0.7 topic verdicts were mostly off-topic (arrests, agitation); entity stories keep 0.6."""
        assert BARS.topic_match == 0.75
        assert topic_visibility(0.7, 0.9, is_news=True, dated=True, scope="state", bars=BARS) == "hidden"
        assert topic_visibility(0.75, 0.9, is_news=True, dated=True, scope="state", bars=BARS) == "listed"
        assert visibility(0.7, 0.85, sentiment="neutral", is_news=True, bars=BARS) == "listed"

    @pytest.mark.parametrize("value, kind, label", [
        (0.8, "match", "High"), (0.6, "match", "Medium"), (0.59, "match", "Low"),
        (0.9, "confidence", "High"), (0.8, "confidence", "Medium"), (0.79, "confidence", "Low"),
    ])
    def test_levels(self, value, kind, label):
        assert level(value, kind) == label
