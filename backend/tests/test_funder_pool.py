from __future__ import annotations

import json

import pytest

from app.ingest.pool import job, load, worker


def _csv_row(**over: str) -> dict[str, str]:
    row = {c: "" for c in load.COLUMNS}
    row.update(pool_funder_id="acme--indian_csr", category="indian_csr", name="Acme Ltd", rank_in_category="4",
               csr_spend_3y_avg_cr="12.5", ingest_status="pending", export_version="2026-11-27",
               signals='{"aliases": ["Acme"]}')
    row.update(over)
    return row


class TestLoaderRows:
    def test_blank_cells_are_null(self):
        values = dict(zip(load.COLUMNS, load.row_values(_csv_row(cin="", score_total=" ")), strict=True))
        assert values["cin"] is None and values["score_total"] is None
        assert values["rank_in_category"] == 4

    def test_signals_stay_json_and_blank_is_empty(self):
        values = dict(zip(load.COLUMNS, load.row_values(_csv_row()), strict=True))
        assert json.loads(values["signals"]) == {"aliases": ["Acme"]}
        blank = dict(zip(load.COLUMNS, load.row_values(_csv_row(signals="")), strict=True))
        assert blank["signals"] == "{}"

    def test_a_missing_column_is_refused(self):
        row = _csv_row()
        del row["signals"]
        with pytest.raises(ValueError, match="signals"):
            load.row_values(row)

    def test_the_update_never_touches_worker_state(self):
        updated = load.UPSERT.split("DO UPDATE SET", 1)[1]
        for column in ("ingest_status", "funder_id", "cin", "attempts", "locked_at", "last_run_id"):
            assert column not in updated


class TestScoutRequest:
    def test_names_the_funder_and_forbids_a_save(self):
        text = worker.request({"name": "Acme Ltd", "category": "indian_csr", "cin": None,
                               "signals": {"aliases": ["Acme"], "parent_name": "Acme Group"}})
        assert "Acme Ltd" in text and "Acme Group" in text and "indian csr" in text
        assert "Do not save" in text

    def test_aliases_read_as_a_list_not_python(self):
        text = worker.request({"name": "Acme", "category": "indian_csr", "cin": None,
                               "signals": {"aliases": ["Acme", "Acme Corp"]}})
        assert "known as: Acme, Acme Corp." in text

    def test_summaries_are_read_from_task_results_only(self):
        from langchain_core.messages import AIMessage, ToolMessage

        state = {"messages": [
            AIMessage("hi"),
            ToolMessage(json.dumps({"slug": "acme-ltd", "fact_count": 3}), tool_call_id="1", name="task"),
            ToolMessage("not json", tool_call_id="2", name="task"),
            ToolMessage(json.dumps({"slug": "x"}), tool_call_id="3", name="read_file"),
        ]}
        assert [s["slug"] for s in worker.summaries(state)] == ["acme-ltd"]


class TestScoutMemory:
    async def test_a_row_s_thread_is_dropped_when_it_ends(self, monkeypatch):
        from langgraph.checkpoint.memory import InMemorySaver

        scout = worker.Scout.__new__(worker.Scout)
        scout.saver = InMemorySaver()
        dropped = []
        monkeypatch.setattr(scout.saver, "delete_thread", dropped.append)

        async def boom(text, config):
            raise RuntimeError("cut off")

        monkeypatch.setattr(scout, "_until_done", boom)
        with pytest.raises(RuntimeError):
            await scout.research({"pool_funder_id": "acme--indian_csr", "attempts": 2, "name": "Acme",
                                  "category": "indian_csr", "cin": None, "signals": {}})
        assert dropped == ["funder-pool-acme--indian_csr-2"]


class TestVerdict:
    @pytest.mark.parametrize(("status", "expected"), [
        ("complete", "done"), ("partial", "done"), ("not_found", "needs_review"), ("wrong_entity", "needs_review")])
    def test_only_research_that_found_the_funder_is_done(self, status, expected):
        assert job.verdict({"status": status})[0] == expected

    def test_a_website_match_is_recorded_as_an_identifier(self):
        assert job.method("website") == "identifier"
        assert job.method("exact") == "exact"


class TestPick:
    def _r(self, slug, name, status="partial", cin=None):
        return {"slug": slug, "entity_name": name, "status": status, "cin": cin}

    def test_the_row_s_own_funder_beats_a_parent_with_a_cin(self):
        saved = [self._r("acme-ltd", "Acme Ltd", cin="L1"), self._r("acme-foundation", "Acme Foundation")]
        assert job.pick(saved, "acme foundation")["slug"] == "acme-foundation"

    def test_wrong_entity_is_passed_over_and_a_cin_preferred_otherwise(self):
        saved = [self._r("a", "Acme", "wrong_entity", "L9"), self._r("b", "Acme"), self._r("c", "Acme", cin="L2")]
        assert job.pick(saved, "Acme")["slug"] == "c"

    def test_the_canonical_name_counts_as_a_match(self):
        saved = [{"slug": "g", "entity_name": "Acme Group", "canonical_name": "Other", "status": "complete", "cin": "L9"},
                 {"slug": "l", "entity_name": "Acme Limited", "canonical_name": "Acme Ltd", "status": "partial",
                  "cin": None}]
        assert job.pick(saved, "Acme Ltd")["slug"] == "l"

    def test_several_researched_and_none_named_picks_no_cin(self):
        saved = [self._r("g", "Acme Group", cin="L9"), self._r("l", "Acme Limited")]
        picked = job.pick(saved, "Acme Ltd")
        assert picked["cin"] is None and job.verdict(picked)[0] == "needs_review"

    def test_one_research_under_another_spelling_is_still_the_row_s(self):
        assert job.pick([self._r("l", "Acme Limited", cin="L1")], "Acme Ltd")["cin"] == "L1"
