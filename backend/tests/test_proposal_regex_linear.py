"""The proposal regexes CodeQL flagged as polynomial: linear on a hostile string, unchanged on a real one."""

from __future__ import annotations

import re
import time

import pytest

from app.proposals import assemble, fill, readiness, research, trace

N = 50_000


def fast(fn, *args):
    started = time.monotonic()
    fn(*args)
    assert time.monotonic() - started < 1.0  # each took 1.5-30 s before


@pytest.mark.parametrize("pattern", [trace.GAP, readiness._GAP, fill._GAP, fill._YOU, assemble._LEFT])
def test_a_run_of_open_gaps_is_linear(pattern):
    fast(pattern.findall, "[Add:" * N + "[You fill:" * N)


@pytest.mark.parametrize("text", ["[Add:" * N, "9" * N + "x", "1.5" * N])
def test_extract_is_linear(text):
    fast(trace.extract, text)


def test_dropping_cites_after_a_long_run_of_space_is_linear():
    fast(assemble.plain, "\t" * N + "x")
    fast(research.case_text, {"sections": {"A1": {"text": " " * N + "x"}}})


@pytest.mark.parametrize("text", ["a ⟦k1⟧ ⟦k2⟧.", "x\t ⟦k12⟧y", "no marks", "⟦k3⟧ lead", "", "a\n⟦k1⟧"])
def test_drop_cites_matches_the_old_regex(text):
    assert trace.drop_cites(text) == re.sub(r"[ \t]*⟦k\d+⟧", "", text)
    assert trace.drop_cites(text, None) == re.sub(r"\s*⟦k\d+⟧", "", text)


def test_gaps_and_amounts_still_read_as_before():
    text = "We need [Add: the 2024 baseline] and [You fill: a name]; it costs ₹2.4 crore, x12.5 lakh."
    assert trace.GAP.findall(text) == ["[Add: the 2024 baseline]"]
    assert assemble._LEFT.split(text)[1::2] == ["[Add: the 2024 baseline]", "[You fill: a name]"]
    assert trace._amounts(text) == [("2.4", "crore"), ("12.5", "lakh")]
    assert trace._no_amounts("₹2.4 crore for 300 girls") == "₹  for 300 girls"


OLD_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(lakhs?|lac|crores?|cr)\b")


@pytest.mark.parametrize("text", ["₹2.4 crore and ₹42 lakhs", "12.5lakh, 3 cr, 2024-25", "9.x lakh", "crore 7",
                                  "₹2,40,00,000 over 3 years", "a1 lac b22.75 crores"])
def test_amounts_match_the_old_regex(text):
    assert trace._amounts(text) == OLD_AMOUNT.findall(text)
    assert trace._no_amounts(text) == OLD_AMOUNT.sub(" ", text)
