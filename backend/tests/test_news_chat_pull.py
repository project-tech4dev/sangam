"""A news pull from chat: staff decide, the goal is kept, other sources are refused out loud."""

from app.ingest import runner
from app.ingest.tools import pipeline_tools


async def test_the_goal_and_the_runner_reach_the_run_and_other_sources_are_refused(monkeypatch):
    seen, items = {}, []

    async def create_run(pool, **kw):
        seen.update(kw)
        return 7

    async def execute_run(pool, run_id, deps, **kw):
        return {"run_id": run_id, "status": "finished"}

    async def item(conn, run_id, source, kind, status, **kw):
        items.append((run_id, source, status))

    class Conn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Pool:
        def connection(self):
            return Conn()

    monkeypatch.setattr(pipeline_tools, "get_pool", lambda: Pool())
    monkeypatch.setattr("app.ingest.news.pipeline.create_run", create_run)
    monkeypatch.setattr("app.ingest.news.pipeline.execute_run", execute_run)
    monkeypatch.setattr("app.ingest.news.pipeline.Deps.from_settings", classmethod(lambda cls, s: None))
    monkeypatch.setattr(runner, "_item", item)
    out = await pipeline_tools._news_pull(None, goal="latest news", started_by="u1", others=["india_csr"])
    assert seen["goal"] == "latest news" and seen["started_by"] == "u1" and seen["org_ids"] is None
    assert items == [(7, "india_csr", "refused")] and "finished" in out


def test_one_list_says_what_runs():
    assert "tavily_news" in runner.RUNNABLE and set(runner.ADAPTERS) <= runner.RUNNABLE


async def test_the_plan_for_a_news_pull_gives_searches_and_cost(monkeypatch):
    from datetime import date

    from app.ingest.news.feeds import Subject

    async def subjects(pool, **kw):
        return [Subject("org", 1, "a", "Org A"), Subject("org", 2, "b", "Org B", searched_through=date.today())]
    monkeypatch.setattr("app.ingest.news.pipeline.plan_subjects", subjects)
    monkeypatch.setattr(pipeline_tools, "get_pool", lambda: None)
    line = await pipeline_tools._news_plan_line(None)
    assert "2 records" in line and "searches" in line and "$" in line and "1 go back 90 days" in line


def test_naming_no_source_never_means_a_news_pull():
    """No sources means the adapters; a news pull costs money, so it runs only when named."""
    assert "tavily_news" not in runner.runnable_for(None)
    assert "tavily_news" not in runner.runnable_for([])
    assert "tavily_news" in runner.runnable_for(["tavily_news"])
