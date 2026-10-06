"""The loader refuses a criteria file that would produce a wrong answer, before anything runs."""

from __future__ import annotations

import copy

import pytest

from app.matching.config import DEFAULT_PATH, CriteriaError, content_hash, load_yaml, parse_criteria


@pytest.fixture
def raw():
    return copy.deepcopy(load_yaml(DEFAULT_PATH)[1])


def refuses(raw, needle):
    with pytest.raises(CriteriaError) as err:
        parse_criteria(raw)
    assert needle in str(err.value), str(err.value)


def test_the_shipped_file_loads():
    criteria, raw = load_yaml(DEFAULT_PATH)
    assert criteria.version == raw["version"]
    assert sum(c.weight for c in criteria.weights.values()) == 100


def test_unknown_evaluator(raw):
    raw["checks"][0]["evaluator"] = "vibes"
    refuses(raw, "unknown evaluator 'vibes'")


def test_bad_params(raw):
    board = next(c for c in raw["checks"] if c["code"] == "board")
    board["params"] = {"count": "three"}
    refuses(raw, "board")


def test_extra_param(raw):
    board = next(c for c in raw["checks"] if c["code"] == "board")
    board["params"]["colour"] = "blue"
    refuses(raw, "board")


def test_group_cycle(raw):
    raw["groups"]["a"] = {"all": ["b"]}
    raw["groups"]["b"] = {"any": ["a"]}
    refuses(raw, "cycle")


def test_duplicate_code(raw):
    raw["checks"].append(dict(raw["checks"][0]))
    refuses(raw, "defined twice")


def test_group_naming_an_undefined_member(raw):
    raw["groups"]["fit"]["of"].append("nope")
    refuses(raw, "'nope'")


def test_unknown_selector(raw):
    raw["applies"]["statutory"] = {"star_sign": ["leo"]}
    refuses(raw, "selector")


def test_unknown_ranking_key(raw):
    raw["ranking"].insert(0, "vibes")
    refuses(raw, "ranking key 'vibes'")


def test_ranking_must_end_in_funder_id(raw):
    raw["ranking"].remove("funder_id")
    refuses(raw, "funder_id")


def test_weights_must_total_100(raw):
    raw["weights"]["fit"]["weight"] = 39
    raw["weights"]["fit"]["checks"]["area"] = 19
    refuses(raw, "total 100")


def test_category_weight_equals_its_checks(raw):
    raw["weights"]["fit"]["checks"]["area"] = 21
    refuses(raw, "fit")


def test_weight_on_an_undefined_check(raw):
    raw["weights"]["fit"]["checks"].pop("area")
    raw["weights"]["fit"]["checks"]["nope"] = 20
    refuses(raw, "'nope'")


def test_partial_level_the_evaluator_does_not_emit(raw):
    raw["partial"]["area"]["block"] = 0.9
    refuses(raw, "'block'")


def test_engine_api_mismatch(raw):
    raw["engine"] = 99
    refuses(raw, "engine")


def test_content_hash_ignores_key_order(raw):
    reordered = dict(reversed(list(raw.items())))
    assert content_hash(raw) == content_hash(reordered)
    raw["version"] += 1
    assert content_hash(raw) != content_hash(reordered)
