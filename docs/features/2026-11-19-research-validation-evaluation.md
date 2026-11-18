# Import research: separate execution, validation and evaluation

Status: **draft for brainstorming**, nothing built. Part of #325 (epic #335). Replaces the PR B plan (`2026-11-18-researcher-saves-once.md` on `fix/researcher-saves-once`), which fixed or removed the grader without measuring it.

## Context

Every Scout researcher sends its ~6k-token `save_research` payload about three times. Code refuses one send for an unanswered field. The Haiku research grader asks for another, and that revision usually changes nothing. The direction: **research execution, deterministic validation and quality evaluation become three separate layers.** Compared with fixing or removing the grader outright, this plan adds:
- a human-labelled baseline before the grader goes;
- a fair grader-on vs grader-off comparison;
- an authoritative save receipt;
- real concurrency guarantees;
- an evaluator that sees the source text;
- a rollback switch.

Keep it simple: reuse Settings, the source archive, Langfuse and the existing upsert, with no new dependencies.

The evidence below came from read-only Langfuse queries over every grader verdict and every `save_research` call since 1 Oct.

## Evidence (Langfuse, 1 Oct – 18 Nov)

**1. The grader's measured value on today's code is zero.** First-grade "needs revision" verdicts, split by when the code checks arrived:

| Period | Fail rate on first grade | Genuine improvement | Structural | Cosmetic | No change | Made worse |
|---|---|---|---|---|---|---|
| Before #194 (to 12 Oct) | 74 / 89 | 10 | 21 | 16 | 24 | 1 |
| #194 to #364 (13 Oct – 3 Nov) | 15 / 18 | 3 | 3 | 2 | 4 | 3 |
| After #364 (from 4 Nov) | **6 / 6** | **0** | 0 | 3 | 0 | **3** |

- **The cases made worse:** a true `not_reached` gap relabelled `not_stated` or `blocked` (Gracious Life, Tata Trusts, Diya, Better Life), and Interglobe losing findings (55→49).
- **"Findings added" is mostly more research:** in 5 of 7 cases the researcher read new pages (Wipro 55→81 with 12 new sources). The rubric forbids that, and more findings is not better research.
- **Cost of a revision:** about 77 s (median, n=87).
- **Caveat:** after #364 there are only 6 cases, all local. That's why M3 compares grader-on and grader-off directly.

**2. Researchers that end with no accepted save:**
- Before #364: 17 of 134, even with the grader on.
- After #364: 1 of 8.

The grader's "send back" turned "nothing saved" into "saved" 6 times, all before #194.

**3. Content errors go uncaught.** A model reviewed 21 accepted saves and found 26 candidate issues, 4 of them high severity. **No person has confirmed them.** The grader flagged none. Examples:
- Dasra: ₹200 crore it only channelled, saved as its own CSR spend.
- ASHA: Goonj saved as a funder from a "linkage".
- SESTA: FCRA `not_found`, though its source "does not state" it.

**4. Data-loss and identity risks in `save_research`** (`tools/research_tools.py:373-435`, `0016_entity_research.sql`):
- The overwrite guard compares only finding counts.
- The pre-check and the write happen on separate connections.
- The key is `UNIQUE (slug, researched_on)`, with the slug derived from `canonical_name`. "Altruism Society" and "Altruism Society Honour Assistance" became two rows.
- `resolved_org_id` and `resolved_funder_id` exist but are set only at promotion (`catalog/promote.py:117`).

**5. Facts the design reuses:**
- Every page read is kept in the source archive:
  - Web pages: `research_tools.py:211`.
  - Documents: `research_tools.py:288`.
  - Key: `<url-hash>/<content-sha256>-<name>` (`integrations/storage.py:150`).
- So an evaluator can read the original text.
- No ingest tool returns a LangGraph `Command` today.
- `mask_payload` (`integrations/tracing.py:73`) redacts only db rows, and only when `LANGFUSE_MASK_TOOL_RESULTS` is on. **Staff-sheet quotes in `save_research` inputs already reach Langfuse today.**

## Design

```
supervisor ── task ──► entity-researcher (execution: read, save)
                              │ save_research(payload)
                              ▼
          validation (backend, deterministic, in the tool; errors return to the model in-loop)
            exact refusals │ warn-only lints │ atomic idempotent write
                              │
                              ▼  NEW receipt {row_id, slug, fact_count, concepts, status, kind, dropped:[...]}
          CHANGED summary fields ← receipt (never the model); no receipt → saved=false, fact_count=0
          grader: behind RESEARCH_GRADER flag (on → off → removed)
                              │
                              ▼  (async, never blocks)
          evaluation: finding_supported judge on ALL high-risk findings,
          given the archived source text around the quote → Langfuse score
```

- **Receipt, not a lookup.**
  - `save_research` returns a `Command` that updates a researcher-private state key (`research_receipt`) and sends the `ToolMessage`.
  - A small after-agent step copies the receipt into the structured `ResearchSummary`. It doesn't jump.
  - The key must not reach the parent. Parallel researchers writing one public key would conflict. That's the reason `ResearchRubric` keeps `rubric` out of state; verify this in M1.
- **Drop the send-back hook for now.** Every validation failure already returns to the model inside the tool, where it retries. The one case a tool can't catch is a researcher that never calls save. After #364 that was 1 of 8. With the receipt, the supervisor sees `saved=false` and already decides what to do next. Add a no-model send-back only if M3 shows a no-save rate above 5%.
- **Atomic write for new and existing rows.**
  - Move the guard into the existing statement: `INSERT … ON CONFLICT (slug, researched_on) DO UPDATE … WHERE <guard> RETURNING …`.
  - One statement is atomic for both an insert and an update. No returned row means the guard refused.
  - `SELECT … FOR UPDATE` can't lock a row that doesn't exist yet, so it isn't used. Pin this with an integration test of two concurrent saves, for a new row and for an existing row.
- **Correction vs accidental loss.**
  - The guard compares finding keys (concept, field, fiscal year), not counts.
  - A save that would drop an existing key is refused, and the refusal names the keys. With `replace=true` and a `replace_reason` the save goes through, and the receipt lists `dropped`.
  - An identical payload changes nothing and returns the same receipt.
  - No metric rewards having more findings.
- **Stable identity, kept small.**
  - When the supervisor has matched the entity in the catalog, the task passes `org_id` or `funder_id`. The save writes `resolved_*_id` straight away.
  - The slug is pinned to the task's entity name, not the model's `canonical_name`.
  - A uniqueness key on the id needs a migration. It's left out unless M0 finds duplicate rows for the same entity more than rarely, which we count from history.
- **High-risk findings are chosen by rule, not at random.** The judge checks every:
  - identifier (FCRA, 12A, 80G, CSR-1, PAN, CIN, Darpan);
  - money figure;
  - funder or partner relationship;
  - entity kind.
- **The evaluator sees the source.** For each finding, it gets the archived text around the quote, about ±1,500 characters, plus the value and the researcher's quote.
  - A quote that doesn't appear in the archived text is a deterministic lint (warn), not a judge call.
  - A finding from a staff sheet is never sent.

## Datasets: three, kept separate

| Set | What | Where | Used for |
|---|---|---|---|
| **A. Research tasks** | 6 Import tasks: 2 funders, 3 NGOs, 1 identity trap (KABIL or Altruism Society), each with fixed sources (web + library) | a list in the scratch harness | grader-on vs grader-off runs, 3 repeats each |
| **B. Finding labels** | 40 historical saves (about 200 findings), each tagged with its date. Labels: supported? right gap reason? right entity and kind? I draft them and the user confirms in a Langfuse annotation queue. Split into 20 dev saves and 20 held-out saves | Langfuse dataset `research-findings`, staff findings dropped | evaluator precision/recall/κ (held-out, reported once) and the human error baseline |
| **C. Fixtures** | Synthetic or public-only payloads for each refusal, lint, guard and race case | `backend/tests/` | unit and integration tests, no network |

## Confidentiality: check each place

| Place | Today | Plan |
|---|---|---|
| Traces | Staff quotes reach Langfuse through `save_research` input | **Decided: accepted as is.** Langfuse is our own vendor and access is limited, so there's no masking change |
| Datasets (B) | — | Drop findings where `is_staff_source_url` is true before upload, and test that |
| Fixtures (C) | — | Synthetic or public organisations only |
| Evaluator requests | — | Filter staff findings out before the call, and test that. The archive excerpt comes only from public sources |

## Milestones (stacked PRs, a review between each)

**M0: Baseline and sets (no app code).**
- Build sets A–C.
- Get a person's labels on set B. That gives the **human error baseline**: the high-severity rate per save and per finding.
- Count duplicate entity rows in history.
- **Exit gate:** 40 saves labelled, with the dev/held-out split frozen.

**M1: Flag, receipt and text fixes.** The grader stays **on** by default.
- **Flag:** `RESEARCH_GRADER` in `core/config.py`; on wraps `research_rubric(utility)` in `ingest/agent.py:329`. This is also the rollback switch.
- **Receipt:** returned by `save_research` and copied into the summary.
- **Rubric fixes, so the grader-on arm is fair:**
  - rule 2 allows `not_reached`;
  - rule 4 reads the counts from the receipt.
- **Skill line:** unstated themes, populations and lenses are `not_stated` gaps.
- **Eval:** `test_import_evals.py` accepts `not_reached`.
- **Exit gate:**
  - tests and ruff pass;
  - a local Import with the flag both on and off produces a receipt whose summary matches the database row.

**M2: Validation and an atomic save.**
- **Exact refusals:**
  - PAN pattern;
  - an identifier saved as `not_found` needs `check_method="registry"` (`finding_types.py:783-788`);
  - `sources_read` must be non-empty when there are findings.
- **Warn-only lints:** returned in the receipt and sent to Langfuse as `research_lint`:
  - a gap reason that doesn't match its detail's wording;
  - "since", "cumulative" or "channelled" next to a single-year money figure;
  - `csr_year` on an entity that isn't bound by Section 135;
  - a quote that isn't in the archived text.
- **Write:** the atomic guarded upsert, key-based loss guard, no-op on an identical payload, pinned slug, and early `resolved_*_id`.
- **Exit gate:**
  - on set C, exact refusals have 0 false positives;
  - on set B (dev), report each lint's precision;
  - the race tests pass for new and existing rows.

**M3: Evaluator, in code (like `answer_audit`).**
- `finding_supported`: one Haiku call per save, after an accepted save, covering all its high-risk findings with their source excerpts. It sends one Langfuse score per finding on the `save_research` observation.
- **Tuning:** on set B dev.
- **Reporting:** on held-out, once — precision and recall on the "unsupported" class, plus agreement and Cohen's κ.
- **Exit gate:** on held-out, precision ≥ 0.8, recall ≥ 0.7 and κ ≥ 0.6. Otherwise the score stays visible in Langfuse and nothing acts on it.

**M4: Grader-on vs grader-off.**
- Run set A, 6 tasks × 3 repeats × 2 arms, on the local DB. Today's rows for those slugs are cleared between runs, local only. Estimated **about $20–25, approved at 3 repeats.**
- Quality is judged by the calibrated evaluator, with a person checking every high-risk disagreement.
- **Decision rule:** flip the production default to off only if grader-off is no worse on human-checked high-severity errors and better on saves, cost and time.
- **Exit gate:** the decision and its numbers are written in the PR body.

**M5: Remove the grader** after 2 weeks or 10 production Imports with the flag off and no regression in `finding_supported` or `research_lint` rates. Delete `ResearchRubric`, `all_passed`, `digest_saves`, `_log_evaluation`, `research_rubric.md` and the flag. Update the docs.

## Exit criteria: prevention vs detection

| | Measure | Baseline | Target |
|---|---|---|---|
| Prevention: quality | High-severity errors per saved row (human-labelled) | M0 | grader-off ≤ grader-on (M4); ≤ half of M0 after M2's checks |
| Prevention: reliability | Saves per researcher / summary = row / findings lost without `replace` / no-save rate | 3 / unchecked / possible / 1 of 8 | ≤ 2 (median 1) / 100% / 0 / ≤ 5% |
| Prevention: cost | Researcher cost per organisation (A/B means over 3 repeats) | M4 grader-on arm | grader-off lower |
| Prevention: latency | Researcher wall time | M4 grader-on arm (about 77 s per revision) | grader-off lower |
| Detection: evaluator | Precision / recall / κ on held-out set B | none | ≥ 0.8 / ≥ 0.7 / ≥ 0.6 |
| Detection: lints | Precision per lint on set B dev | none | report; drop a lint below 0.5 |

## Verification

- **Every PR:**
  - `cd backend && pytest -m "not integration"`;
  - `pytest -m integration` for the race tests;
  - `ruff check .`;
  - `/code-review` and `/security-review`.
  - Offer `make wiki-update`; don't run it.
- **M1 and M4:** `import_baseline.py` and `import_report.py` (saves, refusals, cost by agent, wall time), and the receipt checked against `SELECT … FROM entity_research` on the local DB.
- **M3:** an SDK experiment on `research-findings` (held-out) that reports precision, recall and κ.
- **Confidentiality:**
  - unit tests that staff findings never reach the dataset builder or the evaluator request;
  - a manual check of one dataset item and one evaluator trace.
