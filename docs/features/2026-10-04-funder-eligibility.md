# A funder's eligibility criteria, and the calls they attach to

*2026-10-04*

Two asks, one piece of work: store the eligibility criteria a funder sets for NGOs, and —
when no RFP is recorded for that funder — pull the open calls too. Eligibility lives in two
places for a reason (a standing policy bar and a per-call requirement), and today the second
is researched by a concept no skill ever tells anyone to look for.

## What already exists

**The eligibility pull.** `funder-intake-research/SKILL.md` asks for it twice, and carefully:

- **field 4** — "Stated eligibility, as two separate values": the *statutory restatement*
  (Rule 4 of the Companies (CSR Policy) Rules copied into the policy — 12A/80G/CSR-1, three
  years track record) and *the funder's own additional bar*, in the funder's own words. The
  split is the point: a funder that only restates the law has no bar of its own, and
  reporting those two as one list says something false.
- **field 6** — hard disqualifiers: thresholds the funder says get an application rejected
  outright. The skill explicitly keeps these out of field 4.

So for eligibility the pull is written and the storage is the task. For RFPs it is the other
way round — the storage is built and the pull was never asked for.

**The RFP storage.** `rfp` is a promotable concept with a finding, a record, a writer and a
natural key (`0019` added `rfps_identity`). `research_records.py` says why it exists at all:
*"`rfps` has had `deadline`, `amount_min`, `amount_max` and `eligibility` since the baseline
schema, and no concept pointed at them — so nobody was ever asked to look for one."* The
concept now exists; the **instruction** still does not. The ten fields never ask for the
call itself — field 9 classifies a page as live call *or* historical disclosure, which is a
classification, not a record. A researcher following the skill exactly produces zero `rfp`
findings, however many calls the funder has published.

## Why `rfps.eligibility` is not enough

`docs/DATA_PLATFORM.md` row 16 ("NGO eligibility criteria") points at `rfps.eligibility`,
and that path is real and wired end to end — finding, expectation, record, writer. Two
things are wrong with it for this purpose:

1. **It hangs off a call, and most funders have no call.** The skill's own field 9 says most
   "CSR information" pages are statutory annexures describing money already spent, and field
   1 treats "no stated route" as a real and common finding. A funder with a published
   eligibility policy and no live RFP has nowhere to put it. It is the funder's standing
   posture — exactly the distinction migration `0019` already drew for grant size:
   *"Deliberately on funders and not on rfps: these describe the funder's posture across all
   its giving, where `rfps.amount_min/max` describe one call."*
2. **It flattens the split the skill worked to create.** `list[str]` becomes
   `{"requirements": [...]}` in one jsonb blob with one `source_url` for the whole row.
   Statutory restatement, the funder's own bar and a hard disqualifier arrive as three
   indistinguishable strings, and the per-value `evidenced | claimed` the skill demands has
   nowhere to go. `catalog-mapping` already admits half of this: hard disqualifiers are
   listed as **no home**.

## Where a stored fact goes to die

Three readers decide whether a new row is worth creating, and each is a place this change
has to touch:

- **`funder_dossier`** (`catalog_tools.py`) — eleven sections, **no `rfps` query**. The
  catalog-writer's step 2 exists precisely to catch "a promotion that reports six rows and a
  dossier that shows none", and an RFP write fails that check today for a reason that is not
  a bug in the write. It is also why "are the RFPs there?" cannot be answered at the point
  it is acted on. (`research_goals` *does* print `rfp -> rfps: NOT RECORDED`, via
  `_held_per_concept` — half the machinery is present.)
- **`brief.py` `headline()`** — an if/elif over `concept` that renders each saved finding
  into the published research brief. A concept with no branch is researched and never shown.
- **`expectations.py` `expected_fields()`** — derives a concept's researchable fields from
  the **SQL catalog entry**, skipping `heavy` columns. A concept with no catalog entry
  produces an empty field list in `research_goals`, so the researcher is never told to look.

### The warning: migration 0019

`0019` added five funder-posture columns — `intake_mode`, `funds_external`,
`typical_duration_months`, `grant_size_min`, `grant_size_max`. A repo-wide grep finds them in
`docs/DATA_PLATFORM.md` and the migration file **and nowhere else**: no finding, no
expectation, no writer, no promotion, and no entry in the SQL catalog. Nothing writes them
and Ask Sangam cannot see them.

The drift is silent by construction: `verify_against_db()` compares catalog → database only,
so a catalog that is *behind* the schema raises nothing. (`undeclared_tables()` logs, and
only for whole tables.)

This is scoped out of this change, but it sets the exit gate: **a finding promotes to a row
that `funder_dossier` reads back**, never "the migration file exists".

## Decision

**A child table, `funder_eligibility`, one row per criterion — not jsonb on `funders`.**

A jsonb column would carry one `source_url` for every criterion in it, and `FindingBase`
makes `evidence` + `source_url` + `confidence` mandatory *per finding* — the skill's "every
value carries its exact source URL, including 'not stated'" is a per-value rule. One blob
throws that away on arrival. The repo's idiom for a funder fact is already a child table
with per-row provenance and a `UNIQUE NULLS NOT DISTINCT` natural key: `funder_partners`,
`funder_locations`, `funder_csr_spend`, `funder_footprints`.

`rfps.eligibility` stays exactly as it is. A requirement printed in one call is not the same
claim as a standing policy bar, and `catalog-mapping` says which is which.

**The calls get pulled by instruction, not by new plumbing.** Nothing in the `rfp` path
needs building. What it needs is an eleventh field in `funder-intake-research` telling the
researcher to pull the call when field 9 says there is one, and a `funder_dossier` section
so "not recorded" is visible before and after.

**`kind` carries field 4's split, with three values:** `statutory_restatement`, `own_bar`,
`disqualifier`. The scope line is drawn explicitly: **the document checklist (field 5) stays
out.** "Submit an audited balance sheet" is *what to send*, not *who may apply*, and a
published checklist can run to 32 items — it would outnumber the eligibility rows and make
"how many bars does this funder set" unanswerable. Adding `'document_required'` to the CHECK
later is a one-line migration against the same plumbing.

## The work

### M1 — the row exists, and a finding reaches it

*Exit gate: a `funder_eligibility` finding saved through `save_research` and promoted
produces rows in the table, with provenance populated.*

1. **`db/migrations/0021_funder_eligibility.sql`** — provenance set follows
   `funder_partners`, which is the live idiom for this family.
2. **`app/agent/tools/sql/catalog.py`** — the table and its columns. **Second, not last**:
   `expected_fields()` derives from `CATALOG[CONCEPT_TABLES[concept]]`, so without the entry
   the next step has nothing to derive from. `kind` carries a `values=(...)` tuple, which is
   where the enum is stated once for both the researcher's brief and the CHECK constraint.
3. **`expectations.py`** — a `ConceptSpec`, funder-kind only. `CONCEPT_TABLES`,
   `CONCEPT_TITLES` and `PROMOTABLE` all derive from it.
4. **`research_records.py`** — `FunderEligibilityFinding(FindingBase)`, into `FINDING_MODELS`
   and the `Finding` union.
5. **`records.py`** — `FunderEligibilityRecord`. The record discriminator is itself called
   `kind`, which is why `program.kind` becomes `program_kind`; this finding's `kind` collides
   the same way and needs a `RENAMED` entry (`criterion_kind`).
6. **`writer.py`** — key, updatable tuple, and `write_funder_eligibility()` shaped like
   `write_partner`.
7. **`promote.py`** — five sites: `CONCEPT_RECORDS`, `WRITE_ORDER`, `_row_identity`,
   `_describe`, and the `if/elif` dispatch in `_write_remaining` where the Record is built.

### M2 — it reads back

*Exit gate: `funder_dossier` prints the eligibility section and the rfps section; the
published brief prints the criteria.*

8. **`catalog_tools.py`** — a `_DOSSIER_SECTIONS` entry for `funder_eligibility`, labelled so
   it reads as the funder's stated bars and not as a judgement that any NGO qualifies.
9. **`brief.py`** — a `headline()` branch, printing the criterion prefixed by its kind. This
   is the surface where the statutory/own-bar split earns its keep: "restates the law" and
   "sets its own bar" read completely differently to a fundraiser.
10. **`catalog_tools.py`** — an `rfps` section. This is the "if the RFPs are not there" half
    of the ask: without it a call-level write is unreadable, `write_rfp` fails the
    catalog-writer's check for no good reason, and a researcher cannot tell a funder with no
    calls from a funder nobody has checked. A missing section must read as *not recorded*,
    never *no open calls*.

### M3 — the skills and the docs say so

*Exit gate: the suite is green and a research run against a funder with a published open
call produces at least one `rfp` finding — the thing no run produces today.*

11. **`funder-intake-research/SKILL.md`** — where fields 4 and 6 land, plus a new field 11,
    "the call itself", firing when field 9 came back *live*. It sits after the ten because
    the ten are ordered by how much not knowing the field stalls an NGO, and a specific open
    call sits below the standing questions that decide whether to bother at all. Three rules
    it carries: do not invent a call from a programme page; a closed call is still worth
    recording, because a funder that ran a call last year is a funder with a door; and the
    call's requirements are the call's, not the funder's standing bar.
12. **`catalog-mapping/SKILL.md`** — hard disqualifiers and both eligibility values move out
    of "no home"; `rfps.eligibility` is restated as the per-call case. That skill describes
    its "no home" count as "what tells us which migration to write next" — it just did, so
    the count comes down honestly.
13. **`funder-scan-for-fundraisers/SKILL.md`** — the columns are already right; what changes
    is the "three things never conflated in a cell" block, because *found, not storable*
    shrinks by two categories.
14. **`docs/DATA_PLATFORM.md`** — row 16 repoints at `funder_eligibility`, with
    `rfps.eligibility` named as the per-call case.

**No new tests.** `test_ingest.py` already parametrises over `CONCEPT_TABLES`, asserts
`set(FINDING_MODELS) == set(CONCEPT_TABLES)`, that every finding field reaches a record
field, and that `set(CONCEPT_TABLES) - set(PROMOTABLE) == {"grant"}`. A half-wired concept
fails the existing suite on its own.
