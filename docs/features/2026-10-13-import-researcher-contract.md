# Import: pull every field, keep it in one brief, promote from the brief

Stacked PRs on `feat/research-brief-merged` (#192), one per milestone, each reviewed before the next.
This file is the whole plan; each later PR adds its own section's detail.

## Context
Laying KABIL and Axis Bank Foundation side by side showed research finds far more than reaches the
catalog or the brief: Mission 2 / 4 Million never became programmes, nine SLP component spend lines
were held ("no programme of that name"), seven Axis partners waited for a person, Axis's 23,686 villages
and KABIL's registered address exist only inside quotes. Three causes: the researcher is held to no
field-by-field contract (the pull skills are the supervisor's, and it researches nothing), each run is a
snapshot later runs overwrite or ignore, and promotion holds, drops and fails to link.

Decisions (13 Oct 2026): the brief is the stored record — created on the first run, merged on every later
run, generated only — and `promote_research` reads it. Each fact is a readable line plus a hidden typed
data block, e.g. `{"concept":"programme_spend","program_name":"Rural Livelihoods","amount":{"value":198.29,
"unit":"crore"},"fiscal_year":"FY2024-25"}`; people read the line, promotion reads the block. No evals yet.

## Goals
1. **The researcher pulls a fixed contract, from the skills.** Every field of the brief's layout ends as a
   finding (quoted, sourced, with page) or a gap (`not_stated` / `blocked`, naming the source), plus
   anything else important the source states.
2. **One brief per entity is the record.** Every run merges in; nothing is dropped; every version kept.
3. **Promotion writes the database from the brief, and drops nothing.** Each fact ends written, confirmed,
   contradicted, held (why) or superseded, and the brief says which.
4. **Every source is in the document base**, typed, linked to its programme, cited with a page.

## Catalog mapping
- **Pull list:** the field tables in the two pull skills. Each field names where it lands: `concept.field`,
  or "no column — kept in the brief".
- **DB list:** `expectations.CONCEPTS` (concept → table, rows, columns), derived from the SQL catalog;
  `research_goals` prints it.
- **The join:** a fact's `concept` picks its writer; no model decides where a fact goes.
- **Homes for the missing fields:**
  - existing, no migration: open-call places → `rfp_locations`; spend and footprint district →
    `funder_activity.location_id`; a funder programme's places → footprint rows;
  - one additive migration in M3: `orgs.parent_id`, `orgs.registered_address`,
    `funders.registered_location_id` + `registered_address`, `funders.legal_form`, `funders.founded_year`,
    `org_locations.program_id`, `funder_activity.source_type` + `evidence`, `'component'` in
    `programs.kind`;
  - M4: `document_links` (document → entity, programme, FY, page).

## Milestones
| PR | Milestone | Exit gate |
|---|---|---|
| M1 | Skills are the researcher's contract | an Axis run reads the skill; every field found or gapped; Mission 2/4 Million and the SLP components saved as programmes with figures |
| M2 | The brief is the record; every run merges into it | two Axis runs merge into one brief holding every fact; versions kept; the page renders it |
| M3 | Promote from the brief; drop nothing | Axis and KABIL promoted from their briefs: every fact in a state, the SLP lines and Missions written, no NULL-linked rows |
| M4 | The document base | every source of an Axis run is a typed document linked to its programme |
| M5 | Backfill | KABIL and Axis rebuilt, re-promoted and republished on staging with no model calls |

## M1 — Skills are the researcher's contract
1. **The pull skills move to the researcher.** `skills/research/funder-intake-research` and
   `skills/research/ngo-credential-research`; `ENTITY_RESEARCHER` declares `skills: ["/skills/research/"]`.
   The supervisor's source stays `/skills/`, so it lists the other five and not these.
2. **Each skill is the brief's layout as a field table.** One row per field, the `concept.field` it lands
   in, and the rules: every field an answer; extract what you quote; programmes as a tree with money on
   it; find the documents behind the work (an obligation of ₹10 cr or more → an impact assessment per
   ₹1 cr project); confirm what Sangam holds; name every organisation met, never create or merge one.
3. **The prompt points at the skill.** `prompts/entity_researcher.md` keeps the absolute rules (entity
   confirmation, units, access, staff sheets, keys) and reads the skill for the kind before `research_goals`.
   Its two "What to extract" lists move into the skills.
4. **Schema v3.** `page` on every finding ("p.33", "pp.33-35", "Annexure 4"); `summary` on a `document`
   (what the whole document covers); `unplaced` on the save (a stated fact with no concept: field, value,
   quote, source, page). No migration: from M2 the save merges into the brief, and unplaced facts live in its
   `.md` as data blocks. Until then the save accepts them and stores nothing.
5. **`save_research` refuses a `complete` or `partial` save that leaves a field unanswered.** Every concept
   of the kind has a finding or a gap; every asked year of a year-bound concept has one; every identity
   field has a value or a gap naming it. Example: Axis saved without `rfp` is refused with
   "rfp: no finding and no gap". Partial is held too, because 65 of the 68 staging saves since 1 Oct were
   partial: a field the run never reached is a gap with the new reason `not_reached`, naming what was left
   unread (shown as "not attempted" in the coverage report).
6. **The save lists what it quoted and did not extract.** A number in an `evidence` sentence that no
   finding carries ("23,686 villages") is named in the reply, so the researcher can save it as a metric.
7. CLAUDE.md, `docs/SKILLS.md`: the pull skills are the researcher's.

## Verification
- `pytest -m "not integration"` (fixing tests that pin the skill layout or the finding fields), `ruff`.
- `make migrate` on the local database.
- One Axis run locally: the trace shows the researcher reading the funder skill; the save is refused
  until every field is found or gapped; programmes carry their figures.
