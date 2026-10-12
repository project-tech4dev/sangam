"""Grouping: copies of one event become one story; a story stored earlier keeps its new copies."""

from app.ingest.news import group
from app.ingest.news.group import Candidate


def c(key, title, url="https://a.com/x", summary=""):
    return Candidate(key=key, date="2026-10-01", host="a.com", title=title, summary=summary, url=url)


def test_exact_pass_joins_same_url_or_same_title():
    groups = group.exact_groups([c("s1", "FCRA rules tightened", "https://a.com/1"),
                                 c("n0", "FCRA rules tightened!", "https://b.com/2"),
                                 c("n1", "Different", "https://a.com/1/"),
                                 c("n2", "Unrelated", "https://c.com/3")])
    assert sorted(map(sorted, groups)) == [["n0", "n1", "s1"], ["n2"]]


class Model:
    def __init__(self, reply):
        self.reply = reply

    def with_structured_output(self, schema, **_):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.schema.model_validate(self.reply)


async def test_model_groups_are_repaired_to_cover_every_key_once():
    cands = [c("s1", "A", "https://a.com/1"), c("n0", "A copy", "https://b.com/2"), c("n1", "B", "https://c.com/3")]
    reply = {"groups": [{"label": "A", "keys": ["s1", "n0", "n0"]}, {"label": "junk", "keys": ["zz"]}]}
    out = await group.group(Model(reply), "entity:kabil", cands)
    assert sorted(map(sorted, out)) == [["n0", "s1"], ["n1"]]


async def test_two_stored_stories_are_never_merged():
    cands = [c("s1", "A", "https://a.com/1"), c("s2", "B", "https://b.com/2")]
    out = await group.group(Model({"groups": [{"label": "x", "keys": ["s1", "s2"]}]}), "b", cands)
    assert sorted(map(sorted, out)) == [["s1"], ["s2"]]


async def test_a_model_failure_falls_back_to_the_exact_pass():
    cands = [c("n0", "Same", "https://a.com/1"), c("n1", "Same", "https://b.com/2")]
    out = await group.group(Model(RuntimeError("down")), "b", cands)
    assert sorted(map(sorted, out)) == [["n0", "n1"]]
