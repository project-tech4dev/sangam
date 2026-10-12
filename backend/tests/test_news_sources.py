"""The tavily_news source is registered and runnable; the bars are settings, not screen values."""

from app.core.config import Settings
from app.ingest.sources import DISPATCHABLE, SOURCES, AccessRule


def test_tavily_news_is_a_dispatchable_media_source():
    src = SOURCES["tavily_news"]
    assert src.access_rule is AccessRule.LICENSED_API and AccessRule.LICENSED_API in DISPATCHABLE
    assert src.dispatchable and "news_link" in src.yields


def test_the_bars_default_to_the_spec():
    s = Settings(_env_file=None)
    assert (s.news_listed_match, s.news_listed_confidence) == (0.6, 0.8)
    assert (s.news_public_match, s.news_public_confidence) == (0.7, 0.9)
    assert (s.news_negative_match, s.news_negative_confidence) == (0.9, 0.95)


def test_the_licensed_rule_has_a_strictness():
    from app.ingest.sources import rule_for_host

    rule, src = rule_for_host("api.tavily.com")
    assert rule is AccessRule.LICENSED_API and src.key == "tavily_news"
