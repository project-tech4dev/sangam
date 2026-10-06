---
name: funder-comparison
description: Use when the user names the funders to judge for one organisation — "how does KABIL fit HDFC?", "compare SBI Foundation and Tata Trusts for Goonj", "why is HDFC weak for KABIL?". One named funder gets its checks explained; two or more get a side-by-side table. No narrowing step. To find funders the user has not named, use funder-matching instead.
---

# Named funders, judged and laid side by side

## 1. Resolve the ids

Find the organisation and each named funder by name. If a name could mean two
funders, ask which. A company and its foundation are different funders:
never merge Axis Bank Limited with Axis Bank Foundation.

## 2. Assess every named funder

Launch one funder-assessor per funder with the task tool, all in one message
when your instructions allow that many. Each description names both sides
with their ids. If a task fails, report that funder as "not assessed" with
the error, and never judge it yourself.

## 3a. One funder: explain it

- The tier first, then the assessor's reasons with their citations.
- Then every check, grouped as fit and eligibility: met, fail, or not
  recorded, each with its note and citations.
- Then the gaps, as actions, in the assessor's order.

## 3b. Two or more: one table

| check | HDFC Bank Limited [funder:2] | Funder B [funder:N] |
|---|---|---|
| tier | possible | not enough recorded |
| area | met — Udalguri [org:9] [funder:2] | not recorded |
| reg_12a | met [org:9] | met [org:9] |

- Rows are the check codes either assessment returned. Fit rows come first,
  then eligibility, then the tier on top.
- A check one assessment returned and the other did not, because it does not
  apply to that funder, reads "does not apply" — not "not recorded".
- Under the table: where to start, in one or two sentences, from the tiers
  and the first gap of each.

## Rules that keep it honest

- Repeat each tier and outcome exactly as the assessor gave it.
- An `unknown` is "not recorded". Never "ineligible", "not met" or "poor fit".
- No scores. A tier is Sangam's judgement from the cited rows; say so once.
