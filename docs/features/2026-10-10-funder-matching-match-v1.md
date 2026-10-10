# Funder matching in Ask Sangam: keep the PR's agent approach, move its rules to the spec's match-v1

## Context
PR #100 (`feat/matching-engine`) does funder matching inside **Ask Sangam**, and that approach stays:
- a fundraiser asks in chat;
- the agent loads the `funder-matching` skill;
- one `compare_fit` call judges in code;
- the `funder-shortlist-brief` or `funder-comparison` skill writes it up.

My port to the current schema is on `fix/pr100-port` (`../sangam-pr100`), three commits on top, not pushed.

**What changes is the rules and matching logic.** #100 scores with its own framework:
- gates (Fit, Statutory, Turnover);
- Fit 40 / Compliance 25 / Financial 15 / Governance 10 / Programme 10;
- outcomes met / fail / unknown;
- ranking gate first, then score.

The spec (`features-plans/funder-match/2026-10-08-funder-match-design.md` @ 37cb604) defines **match-v1**:
- seven criteria (theme 25, geography 15, population 15, eligibility 20, relationship 10, funding size 10, capacity 5);
- statuses met / partial / fail / unknown;
- a score out of the judged points, a NULL score when nothing is shared;
- tiers Strong ≥ 75 / Medium 55–74 / Weak < 55;
- a criteria / card / summary / improve shape per funder.

This PR moves #100 onto that. The spec's private tables, `make match` job, API and page are not part of this change. They come later and can reuse the same pure `match()`.

**Decided:**
- A claimed credential counts, with the claimant noted.
- Geography: district 15, state 12, India or region 6.
- Tests follow the spec: unit tests for the rubric and the criteria.

*Approved 2026-10-10. Supersedes `2026-10-07-funder-matching-scored.md`; the shape in `2026-10-07-funder-matching-in-code.md` stays.*

## Architecture

```
 Browser (Ask workspace chat)
   │ "Which funders fit KABIL?"  /  "How does KABIL do against HDFC Bank?"
   ▼
 Next.js /api/copilotkit ──AG-UI──▶ FastAPI /agent ──▶ Ask Sangam (LangGraph deep agent, MODEL)
                                                         │ loads skill: funder-matching            (read_file)
                                                         │
   ┌─────────────────────────────────────────────────────┼──────────────────────────────────────┐
   │ 1. resolve the org        db_query  → org_id 9  [org:9]                       (1 call)     │
   │ 2. compare_fit(org_id=9, funder_ids=None | [7, 2])                            (1 call)     │
   │      agent/tools/matching_tools.py   try/except → "compare_fit failed: …", never raises   │
   │      │                                                                                     │
   │      ├─ load()       repositories/matching.py   fixed SQL, one read-only txn, owner pool   │
   │      │               → OrgProfile · [FunderProfile] · Places                              │
   │      ├─ judge()      agent/rules.py      (pure)  7 criteria per funder:                    │
   │      │               status · points · note · cites [org:N] [funder:N] [activity:N]        │
   │      ├─ score()      agent/rubric.py     (pure)  earned / judged_max → of_100 · tier · NULL │
   │      └─ write-up     agent/match.py      (pure)  card · summary · not_judged · improve      │
   │      → ranked by score desc; not_scored: nothing in common · funder has nothing recorded   │
   │ 3. skill: funder-shortlist-brief (many funders) | funder-comparison (one or two)           │
   │      copies scores, tiers and cites as given; never re-judges, never re-queries            │
   └────────────────────────────────────────────────────────────────────────────────────────────┘
                                                         │
                                                         ▼
 Postgres (read only): orgs, org_locations, org_tags, programs, program_tags, org_identifiers,
   org_financials, documents, contacts, funders, funder_locations, funder_tags, funder_activity,
   tags (+0036 crosswalk), locations
```

**Why this shape:**
- **The agent drives; code decides.** The model picks the org and the funders, and writes the answer. The criteria, points and order come from pure functions, so the same question gets the same scores every run.
- **One call instead of ~35.** One `compare_fit` call returns every fact already cited, so the agent has nothing to re-query and no citation to chase. That is why the subagent version was replaced.
- **Nothing new is exposed.** `compare_fit` reads only tables already in Ask's catalog, so any Ask user could reach the same rows with `db_query`. Nothing is stored.
- **Reusable later.** `match()` returns the spec's `criteria` / `score` / `card` / `detail` shape. A later `make match` job can write those to `funder_matches` without new logic.

## What changes, file by file (`fix/pr100-port`)

| File | Change |
|---|---|
| `backend/app/repositories/matching.py` | **Extend `load()`:** partner and programme lines get `funder_id`, so a relationship is per pair (today they carry only the org). Funders gain `grant_size_min`/`grant_size_max`, `population` tags, and lines with `amount` and `fiscal_year`. The org gains `population` tags and its latest `org_financials.total_income`. Population tags are kept apart from sector tags in `_tag_sets` |
| `backend/app/agent/rules.py` | **Keep** `Places`, the profiles, `Identifier` and `_credential` (HELD/LAPSED, claimed with the claimant noted). **Rework** `_area` → `geography` and `_theme` + `_programme` → `theme`. **Add** `population`, `eligibility`, `relationship`, `funding_size` and `capacity`. **Delete** `judge_org`'s darpan, pan, reg_no, fcra, itr_7, board, team_cvs and projects_3, plus `_foreign` and `PairResult`. The new entry point is `judge(org, funder, places, today) → list[Criterion]` |
| `backend/app/agent/scoring.py` → `rubric.py` | **Replace:** gates, WEIGHTS, AREA_CREDIT and rank_key go. In their place: `RUBRIC_VERSION = "match-v1"`, `CRITERIA` (code, label, max), `status_for(points, max)`, `score(criteria)` → `{earned, judged_max, of_100}` or None, and `tier(score)` |
| `backend/app/agent/assessment.py` | **Replace** `Check`/`FunderAssessment` with `Criterion` (code, label, max, points, status, note, cites) and `Match` (score, tier, card, summary, criteria, not_judged, improve). The validator "met/partial/fail needs a cite" stays; relationship `fail` with `cites: []` is allowed, as the spec says |
| `backend/app/agent/match.py` (new, pure) | `match(org, funder, places, today) → Match`. Builds the card, summary, not_judged and improve from templates |
| `backend/app/agent/tools/matching_tools.py` | `compare_fit` returns match-v1 per funder: score, tier, the card lines, every criterion with points and cites, not_judged and improve. It is ordered by score, NULL last. NULL-score funders appear as a count plus names. The docstring is rewritten (it's a `@tool` docstring, so it can be long) |
| `backend/app/agent/skills/funder-matching/SKILL.md` | Ranking by score, the tiers, Weak or Not scored listed after, never treating unknown as a gap |
| `.../funder-shortlist-brief/SKILL.md`, `.../funder-comparison/SKILL.md` | Gate sections ("Eligible → Unverified → Removed") become tier sections (Strong → Medium → Weak → Not scored). The criterion table becomes the seven match-v1 rows with `pts / max` or "unknown" |
| `backend/app/agent/instructions.md` rules 12–16 | The wording follows the new output: score and tier instead of gate and rank; "unknown is left out, never zero" |
| `CLAUDE.md`, `docs/SKILLS.md` | Describe compare_fit's output as match-v1; no "gates" |
| `docs/features/2026-10-07-funder-matching-scored.md` | Delete (superseded) |
| `backend/tests/test_matching_rubric.py`, `test_matching_rules.py` (new) | Spec unit tests (see Verification) |

## The rules (match-v1, all code)

A status comes from points: `met` at 80% of max or more, `partial` above 0, `fail` at 0 with evidence, and `unknown` with `points: null`.

| Criterion | Max | Rule | Example |
|---|---|---|---|
| Theme | 25 | **Met 25:** a shared sector tag or Schedule VII slug (via the 0036 crosswalk), and the org runs a programme tagged with it. **Partial 15:** a shared tag, but no programme in it. **Fail 0:** both sides tagged, nothing shared. **Unknown:** either side untagged | KABIL × HDFC: `rural_livelihoods` shared, plus programme 12 → 25 met `[org:9][funder:7]` |
| Geography | 15 | **District 15** (met). **State 12** (met). **India or a region 6** (partial). **Fail 0:** both have places, none shared. **Unknown:** either side has none. A funder's registered office doesn't count | Assam state only → 12 met |
| Population | 15 | **Met 15:** a shared `population` tag. **Fail:** both tagged, none shared. Otherwise **unknown** | Locally 0 population tags, so unknown for now |
| Eligibility | 20 | Items are 12A, 80G and 3 audited years, plus CSR-1 when `funder_type` is `corporate_csr`/`corporate_foundation` or `section_135_bound`. Each item is an equal share. Held or claimed earns it, with the claimant noted; lapsed or not on record earns 0. **Unknown** only when the org has no identifier, financial or document rows. An untyped funder: CSR-1 isn't counted, and `not_judged` says so. The funder's own bars (`funder_eligibility` doc) go in `not_judged` with the document cited | 3 of 4 held → 15/20 partial; "CSR Form 1 not on record" |
| Relationship | 10 | **Met 10:** a `funder_activity` line from this funder naming the org, not unconfirmed. **Partial 5:** only unconfirmed lines. **Fail 0, cites []:** none recorded | `[activity:41]` concluded 2024 → 10 met |
| Funding size | 10 | **Met:** `grant_size_min` ≤ the org's latest `total_income`. **Partial:** min ≤ 2× income. **Fail:** beyond that. **Unknown:** no range or no income. Thresholds are constants in `rubric.py` | Locally 0 funders have a range, so unknown |
| Capacity | 5 | Spend or programme lines with an amount, from this funder, in the last 3 fiscal years. **3 years: 5 met. 1–2 years: 3 partial. None: unknown** | One spend line in FY24 → 3 partial |

- **Score:** `of_100 = round(100·earned/judged_max)`. It is **NULL** ("No shared place or theme recorded") when neither theme nor geography is met or partial. This replaces #100's "nothing in common" narrowing and keeps the same meaning.
- **Write-up** (templates in `match.py`):
  - **card:** the top two met criteria by points are fit lines; the two that lost the most points are gap lines.
  - **summary:** the tier, the best fit, where points were lost, and what wasn't judged.
  - **improve:** one action per losing item, with the points it could win back, e.g. "Register CSR Form 1 with the MCA (up to 5 points)".

**Example `compare_fit` line** (one funder, as the model sees it):
```
#1 HDFC Bank Parivartan [funder:7] · corporate_csr · 73/100 Medium (66 of 90 judged)
  ✓ Rural livelihoods is a core theme   ✓ Assam is one of its focus states
  ! CSR Form 1 not on record             ! No past grant or contact recorded
  theme 25/25 met [org:9][funder:7] · geography 12/15 met [org:9][funder:7] · population unknown ·
  eligibility 15/20 partial [org:9] · relationship 0/10 fail · funding_size unknown [funder:7] · capacity 3/5 partial [activity:88]
  not judged: funding size (no grant range); population (no population tags)
  improve: Register CSR Form 1 (up to 5) · Record any contact with HDFC Bank Parivartan (up to 10)
```

## Milestone (one PR: #100, `fix/pr100-port` pushed to `feat/matching-engine`, a fast-forward)
1. Commit the plan doc.
2. Loader changes in `repositories/matching.py`.
3. `rubric.py` and the new `assessment.py` models.
4. `rules.py` with the seven criteria.
5. `match.py`.
6. The `compare_fit` output and docstring.
7. Skills, instructions rules 12–16, CLAUDE.md and SKILLS.md.
8. Unit tests.
9. Push, and rewrite the PR title and body (feat(ask): funder matching to match-v1).

**Exit gate:**
- `pytest -m "not integration"` and `ruff check` pass on the changed files;
- `try_match.py` over the local orgs: `of_100` equals the arithmetic, every met, partial or fail has a cite (relationship fail excepted), and NULL only when theme and geography are both unshared;
- one real chat, "Which funders fit KABIL?", answers with one `compare_fit` call and a brief in tiers;
- `npm run build` passes, since toolLabels is unchanged.

## Later (not this PR)
- The spec's private tables (the next free migration number: another session already uses `0039_research_by` locally), `make match`, the API, the page, the design sync and retiring the fit scores. All reuse `match()`.
- #114 before match results enter Ask's catalog.

## Verification
- **Unit:**
  - rubric: unknown is left out (66/90 → 73), the 75/55 tier thresholds, and the NULL rule;
  - each criterion's statuses from fixed profiles: claimed → met with the claimant noted; lapsed → 0; state → 12; the relationship per funder.
- **Local:** `PYTHONPATH=backend …/.venv/bin/python scratchpad/try_match.py` against `localhost:5433`.
- **End to end:** `make up`, then ask in `/ask`. Check the tool trace shows `db_query` → `compare_fit` → done, and that the answer's cites match the tool output.
