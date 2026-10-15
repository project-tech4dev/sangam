# Funder Match: design

*Proposed 8 Oct 2026. The UI was agreed on a clickable prototype:
https://claude.ai/artifact/H1b4nv5ReQn8mvHg2HhPB5 (version 5). The prototype's data is invented.*

## What it is for

For an organisation, Funder Match ranks the funders it fits best, highest score first. Each one has
a short reason and the full reasoning one click away, and leads to a proposal. It answers two
questions: "who should we approach?" and "why them?". When a funder fits poorly or not at all, it
says so; nothing is hidden.

It is the first item under **Use Cases** in the Ask workspace sidebar. Today that item opens a
"Coming soon" stub (`features/ask/views/FunderMatchView.tsx`).

**Out of scope**
- **Proposals.** "Start a proposal" and "Continue proposal" open the existing Proposals stub. The
  proposal model, guided writing and access rules get a spec of their own.
- **Rerun from the page.** Rerunning a match exists as a job command (below). The staff Rerun button
  is shown but wired up in v2.
- **Trends between runs** ("up from 81"). Left out on purpose.

## Who sees what

Who someone is comes from sign-in. There is no setting for it.

| Signed in as | Organisations shown | Rerun button |
|---|---|---|
| Member or admin of one organisation | That organisation, named, with no picker | No |
| Steward of several organisations | A picker over the organisations they steward | No |
| Sangam staff | A picker over every organisation | Yes (v2) |
| Signed in, no organisation | None. A short note on how to join one | No |
| Signed out | The workspace is not shown (as today) | — |

Anyone shown an organisation can start a proposal for it. That includes stewards: a decision recorded
here, and carried out in the Proposals spec, since today's row-level rules let stewards only read.

## The page

From top to bottom:

1. **Header**
   - The eyebrow "Use Cases" and the title "Funder Match".
   - The organisation: its name, or the picker.
   - A run line: "Latest run 6 Oct 2026 · 43 funders checked · 3 earlier runs".
   - The staff-only **Rerun match** button.
2. **Three summary cards**
   - **Strong fits** (score 75 or more) and **Medium fits** (55–74). Clicking either filters the list;
     clicking again clears the filter.
   - **Proposals started**: the organisation's proposal count, linking to the Proposals page. It shows 0
     until Proposals exist.
3. **Filters**: All fits, Strong, Medium, and Proposal started. The last appears only once Proposals
   exist. The list is always ranked by score, highest first.
4. **One card per funder with a score of 55 or more**
   - **Top row:** rank, the initials disc (`EntityMark`), name and funder type, then the score out of
     100 with a bar and a tier tag.
   - **Body:** two to four short reasons, ✓ for what fits and ! for the main gaps.
   - **On the right:** the proposal button, terracotta **Start a proposal** or sage **Continue
     proposal**.
5. **"Why this score — full reasoning"**, an accordion inside the card. It is loaded only when opened,
   and holds:
   - a plain summary;
   - every criterion with its points and a chip citing the record it rests on;
   - what could not be judged, and why;
   - what would raise the score;
   - which run it came from.
6. **"Weak or no fit"**, folded at the foot. It lists funders scored below 55 with their score, and
   funders checked with nothing to score on as "Not scored". Each has its one main reason, so a
   funder missing from the list above reads as checked, not overlooked.

**Tiers** come from the score and are never stored: Strong ≥ 75, Medium 55–74, Weak < 55. A funder with no
score is Not scored.

**Empty and error states**
- **No run yet for the organisation:** "No match has been run for <org> yet." Staff also see "Run
  one with `make match ORG=<slug>`" until the v2 button works.
- **The detail fails to load:** the accordion says so and offers a retry. The card itself stays.

The page follows CLAUDE.md:
- classes in `globals.css`, no inline styles;
- Lucide icons styled by the `.icon` classes;
- Title Case labels in the sidebar;
- the same PR updates the design system: its components, and a `FunderMatch` page in
  `ui_kits/sangam-web/`.

## Data model

Match results are **private** to the organisation's people (members, admins, stewards) and staff. The
rubric is kept **in code** and versioned there. Two tables. The list reads the first; the second is
read only when a card is opened.

```sql
-- One row per funder per run. All the list needs.
CREATE TABLE funder_matches (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id         uuid NOT NULL,                 -- shared by every row one run writes
  org_id         bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  funder_id      bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  run_at         timestamptz NOT NULL,
  rubric_version text NOT NULL,                 -- the in-code rubric that scored it
  score          smallint CHECK (score BETWEEN 0 AND 100),  -- NULL: checked, nothing to score on
  card           jsonb NOT NULL,                -- {"reasons": [{"kind", "criterion", "text"}]}, see below
  UNIQUE (run_id, funder_id)
);
CREATE INDEX funder_matches_latest ON funder_matches (org_id, run_at DESC);

-- The full reasoning, loaded on demand.
CREATE TABLE funder_match_details (
  match_id bigint PRIMARY KEY REFERENCES funder_matches(id) ON DELETE CASCADE,
  detail   jsonb NOT NULL
);
```

### The two JSON fields, worked through

One match, end to end: **SeSTA × HDFC Bank Parivartan** in a run on 6 Oct 2026. The values are invented,
but they are internally consistent: the score below is computed from the criteria shown.

**The row in `funder_matches`.** This is what the list endpoint reads, one row per funder:

```json
{
  "id": 1042,
  "run_id": "6f1c2a9e-4b7d-4c1e-9a52-0d3b8e7f6a11",
  "org_id": 3,
  "funder_id": 7,
  "run_at": "2026-10-06T02:30:00Z",
  "rubric_version": "match-v1",
  "score": 73,
  "card": {
    "reasons": [
      {"kind": "fit", "criterion": "theme",       "text": "Rural livelihoods is a core theme"},
      {"kind": "fit", "criterion": "geography",   "text": "Assam is one of its focus states"},
      {"kind": "gap", "criterion": "eligibility", "text": "CSR Form 1 not on record"},
      {"kind": "gap", "criterion": "relationship","text": "No past grant or contact recorded"}
    ]
  }
}
```

**The `card` field**
- Two to four short lines, written for a glance: a fact, not a sentence of analysis.
- `kind: "fit"` lines come first and are drawn with ✓; `kind: "gap"` lines are drawn with !.
- `criterion` names the criterion each line came from. The job writes it; the page doesn't show it,
  but it ties every line to a criterion in `detail`, so the short version can never say something
  the full version doesn't.
- The job builds `card` from `detail`:
  - the highest-scoring met criteria become the fit lines;
  - the criteria that cost the most points become the gap lines.
  - Nobody writes the card separately.

**The row in `funder_match_details`.** This is read only when "Why this score" is opened:

```json
{
  "match_id": 1042,
  "detail": {
    "summary": "A medium fit, close to strong. HDFC Bank Parivartan's rural development programme names Assam as a focus state and funds livelihoods, which is SeSTA's core work. Points are lost on CSR Form 1, which Section 135 money requires, and on the lack of any past relationship. Its grant range is not public, so funding size was not judged.",
    "criteria": [
      {"code": "theme", "label": "Theme alignment", "max": 25, "points": 22, "status": "met",
       "note": "Both work on rural livelihoods; SeSTA's women's collectives sit inside Parivartan's 'sustainable livelihoods' theme.",
       "cites": ["org:3", "funder:7"]},
      {"code": "geography", "label": "Geography", "max": 15, "points": 12, "status": "met",
       "note": "Assam is a focus state. No district is named on the funder's side, so this is a state-level match, not a district one.",
       "cites": ["org:3", "funder:7"]},
      {"code": "population", "label": "Target population", "max": 15, "points": 13, "status": "met",
       "note": "Rural households and women; Parivartan does not single out women's groups.",
       "cites": ["org:3", "funder:7"]},
      {"code": "eligibility", "label": "Eligibility & compliance", "max": 20, "points": 14, "status": "partial",
       "note": "12A, 80G and three audited years are on record. CSR Form 1 is not, and a Section 135 funder needs it.",
       "cites": ["org:3"]},
      {"code": "relationship", "label": "Relationship", "max": 10, "points": 0, "status": "fail",
       "note": "No past grant, programme or contact between them is recorded.",
       "cites": []},
      {"code": "funding_size", "label": "Funding size", "max": 10, "points": null, "status": "unknown",
       "note": "Parivartan does not publish a grant range.",
       "cites": ["funder:7"]},
      {"code": "capacity", "label": "Funder capacity", "max": 5, "points": 5, "status": "met",
       "note": "CSR spend reported every year for the last five, and rising.",
       "cites": ["activity:88"]}
    ],
    "score": {"earned": 66, "judged_max": 90, "of_100": 73},
    "not_judged": ["Funding size: the funder publishes no grant range, so these 10 points are left out rather than scored as zero."],
    "improve": [
      "Register CSR Form 1 with the MCA and add it to the Doc Vault (up to 6 points).",
      "Record any contact with HDFC Bank Parivartan; a warm introduction counts under Relationship (up to 10 points)."
    ]
  }
}
```

**How the `detail` fields work**
- `summary`: three or four plain sentences, for someone who reads nothing else. It names the tier, the
  main reason it fits, the points lost, and anything not judged.
- `criteria`: every criterion in the in-code rubric, always in the rubric's order, so two funders read
  the same way side by side.
  - `status` is `met` (full or nearly full points), `partial`, `fail` or `unknown`.
  - An `unknown` criterion has `points: null` and is left out of the total. Unknown is never zero.
  - `note` says what was found, in words, including what is missing.
  - `cites` are the same `[org:N]`, `[funder:N]`, `[activity:N]` markers Ask Sangam uses. The page
    shows them as chips, so every claim traces to a record. An empty list means the finding is an
    absence: nothing was recorded.
- `score`: the arithmetic, stored so the page can show it rather than recompute it.
  - `earned` is the points earned over the judged criteria; `judged_max` is the points that could be
    judged.
  - `of_100` is `round(100 × earned / judged_max)`, and always equals the row's `score`. Here that is
    66 of 90, so 73.
- `not_judged`: each unknown criterion, explained in a sentence.
- `improve`: concrete actions, each with the points it could win back. Shown under "What would raise
  the score".

**A funder with nothing to score on** still gets a row, so "43 funders checked" stays true. It has a
`NULL` score, a one-line card, and a short detail:

```json
{"score": null,
 "card": {"reasons": [{"kind": "gap", "criterion": "overlap", "text": "No shared place or theme recorded"}]}}
```
```json
{"summary": "Not scored. The base records no place or theme in common between SeSTA and Infosys Foundation, so there was nothing to judge.",
 "criteria": [], "score": null, "not_judged": [], "improve": []}
```

**Which field feeds which part of the page**

| Page element | Field |
|---|---|
| Rank, score, bar, tier tag | `funder_matches.score` (tier computed) |
| Name, initials disc, funder type | `funders`, joined by `funder_id` |
| The ✓ and ! lines on the card | `card.reasons` |
| "In short" | `detail.summary` |
| "Criterion by criterion", with citation chips | `detail.criteria` |
| The points arithmetic | `detail.score` |
| "Not judged" | `detail.not_judged` |
| "What would raise the score" | `detail.improve` |
| "From the run of 6 Oct 2026 · match-v1" | `funder_matches.run_at`, `rubric_version` |
| "Weak or no fit" rows | rows with `score < 55` or `NULL`; first line of `card.reasons` |

**Size.** A card is about 0.3 KB; a detail about 2–3 KB. The list for 43 funders is about 15 KB, and a
detail loads in one small request when its card is opened.

**What the page derives instead of storing**
- **Latest run:** the newest `run_at` for the organisation.
- **Funders checked:** the row count for that `run_id`.
- **Earlier runs:** the count of distinct `run_id`s before it.
- **Tier:** computed from the score.

**Access** (row-level security, plus table grants in the style of `0025`/`0027`)
- **Read:** `org_id IN (SELECT app.my_org_ids()) OR (SELECT app.is_staff())`, on both tables. The detail
  rule goes through its match row. Anonymous users get nothing.
- **Write:** none for `authenticated`. Only the match job writes, as the database owner, the way
  ingest does.
- **Not in Ask Sangam's table catalog.** Ask's SQL tools run as the database owner until #114 is
  fixed. Putting these tables in `catalog.py` before that would let any Ask user read every
  organisation's matches. Add them after #114, as a separate decision.

**Provenance.** Matches are computed, not scraped, so they carry `rubric_version` instead of the source
columns. Every criterion's `cites` points at the records it used. The catalog's note on rubric output
records the same exemption.

**Retention.** Every run is kept. At about 43 rows per organisation per run, there is no case for
pruning yet.

## API

Both endpoints sit in a new `funder_matches` resource: router, repository and schema, plus one line in
`api/router.py`. Both run as the caller, so the row-level rules decide. An organisation the caller
cannot see is a 404, the same answer as one that does not exist.

- **`GET /api/funder-matches?org=<slug>`**, behind `require_user`. It returns the latest run:
  ```json
  {"org": {"slug": "sesta", "name": "SeSTA"},
   "run": {"run_id": "6f1c2a9e-4b7d-4c1e-9a52-0d3b8e7f6a11", "run_at": "2026-10-06T02:30:00Z",
           "rubric_version": "match-v1", "funders_checked": 43, "earlier_runs": 3},
   "counts": {"strong": 1, "medium": 2, "weak": 3, "not_scored": 37},
   "matches": [{"id": 1042,
                "funder": {"id": 7, "slug": "hdfc-bank-parivartan", "name": "HDFC Bank Parivartan",
                           "funder_type": "corporate_csr"},
                "score": 73, "tier": "medium",
                "card": {"reasons": [{"kind": "fit", "criterion": "theme", "text": "Rural livelihoods is a core theme"}]}}]}
  ```
  - Ordered by score descending, with NULL scores last.
  - `run` is `null` when the organisation has never been run.
- **`GET /api/funder-matches/{id}/detail`**, behind `require_user`. It returns `detail`.

**The organisation picker** comes from what already exists. A member's or steward's organisations come
from `GET /api/me` (`memberships`); staff use `GET /api/orgs`. No new endpoint.

## The match job

There is one entry point. It runs for every organisation, or for one:

```bash
make match              # one complete run: every organisation against every funder
make match ORG=sesta    # rerun one organisation
```

Like every database target, it follows `ENV`. `make match ENV=staging` writes to the shared database,
so run it deliberately.

`backend/app/matching/` is a new group, per the layout rule in CLAUDE.md. It holds:
- `rubric.py`: the in-code rubric, `RUBRIC_VERSION`, criteria, points and tier thresholds;
- `run.py`: the job and its `python -m app.matching.run [--org slug]` entry point.

For each organisation, the job:

1. Loads the organisation profile once, and every funder profile in bulk. This reuses the profile
   loaders and the pure rule functions of `compare_fit` (#100: `repositories/matching.py`,
   `rules.py`, `scoring.py`).
2. Judges each pair with the rubric into criteria, a score, a card and a detail. It is code only: no
   model call, the same result every time.
3. Writes all of the organisation's rows under one new `run_id` in a single transaction, so a run is
   all or nothing and the page never shows a half-run.
4. Logs counts only: organisations, funders and tiers. It logs no organisation data.

A funder sharing nothing with the organisation still gets a row, with a NULL score and the reason
"Nothing in common recorded". That is what makes "43 funders checked" true.

v2 adds `POST /api/funder-matches/runs?org=<slug>` (staff only) to start the same job from the Rerun
button, and `run_by` on `funder_matches` to record who ran it.

**Order of work**
1. The tables and the job.
2. One complete run against staging, done deliberately, since it writes to shared data.
3. The API.
4. The page and the design-system sync.

## Retiring the old fit scores

The `rubrics`, `rubric_criteria`, `fit_scores`, `fit_score_items` and `score_adjustments` tables are
replaced. Fit scores were public; match results are private, and their rubric lives in code. Removing
them is one migration plus the code that reads them, shipped **after** Funder Match works, in its own
PR:

- **Migration:**
  - drop `proposals.fit_score_id`, then the five tables;
  - drop the grants and row-level rules on them in the same migration.
- **Backend:**
  - the `scores` resource (`api/routes/scores.py`, `repositories/scores.py`, `schemas/scores.py`,
    `tests/test_scores.py`);
  - fit-score reads in `repositories/funders.py` and `repositories/news.py`;
  - the five tables and their defects in `agent/tools/sql/catalog.py`, and the SQL tests that name them;
  - the `[score:N]` marker in `agent/instructions.md` and `agent/build.py`;
  - golden eval cases about fit scores (`tests/evals/cases/golden.jsonl`).
- **Frontend:**
  - the Registry's "Fit scores" tab and `features/registry/ScoreCard.tsx`, on both profile pages;
  - `[score:N]` in `features/ask/components/EvidenceRail.tsx`;
  - `/api/scores` in `app/(agent)/ask/page.tsx`;
  - the sample answer in `features/ask/preview/sample.ts`;
  - the design system's `ScoreCard` component and the Registry and Profile UI-kit pages.
- **Seed and scripts:** `seed/seed.py`, `seed/data/rubrics/v2.json`, `seed/graph_seed.py`, and the
  fit-score count in `scripts/smoke.sh` and `/api/meta/stats`.

Until #114 lands and the match tables enter the catalog, Ask Sangam cannot answer "how well does X
fit Y". The answer then lives on the Funder Match page. That gap is accepted.

## Testing

- **Unit:**
  - the rubric's scoring, including unknown criteria left out of the total and the tier thresholds;
  - the job's row shapes from fixed profiles;
  - the API through `client_for` with the repository patched, covering an empty run, ordering with
    NULL scores last, and a 404 for an organisation the caller cannot see.
- **Integration** (`integration` mark):
  - the row-level rules: member, steward, staff, stranger and anonymous against both tables;
  - one job run against the compose Postgres, then a rerun, checking the earlier run is kept and the
    page reads the new one.
- **Frontend:** `npm run lint` and `npm run build`; the page checked by hand for each role, including
  at phone width.

## Open after this spec

- **Proposals:** model, guided writing, and stewards' write access.
- **v2:** the staff Rerun button, `run_by`, and possibly a runs table.
- **#114:** after it is fixed, whether Ask Sangam's catalog gets the match tables.
- **#100:** it must merge first, or its rule and scoring functions be extracted, so the job does not
  depend on an unmerged branch. Its migrations `0022`/`0024` also collide with existing numbers and
  need renumbering.
