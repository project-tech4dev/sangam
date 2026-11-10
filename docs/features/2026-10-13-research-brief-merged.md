# Research brief: one record from every run, with full programmes

## Context

The brief at `entities/<slug>.md` is rebuilt on every `save_research`, but from **that day's
`entity_research` row only**, so each run drops what earlier runs found:

- KABIL: 5 programmes on 10 Oct, 2 on 11 Oct, 0 on 12 Oct. Its brief now shows no programmes.
- Axis Bank Foundation: 214 findings on 11 Oct, 88 on 12 Oct. The brief lost 126 of them.

Programme lines print only name, kind and parent (`brief.py` `headline()`), though of 288 programme
findings 235 carry a description, 138 themes and 69 populations. And sections follow the concept
registry, not the order the `entity-record` skill sets, and an empty one is dropped.

Out of scope: researching more per programme, and linking a brief whose research slug differs from
the funder's (Misereor).

## Design

**Merge.** `entity_markdown(rows)` takes every row for a slug. Each finding has a key per concept
(programme: name; partner: funder + project + year; CSR year and financials: year; identifier: type;
place: state + district + programme; metric: name + period + programme; otherwise headline + year).
For each key the findings of the **newest run that has it** are kept, all of them, so two sources for
one fact in one run both stay. The header is the newest run's; a "Research runs" section lists each run.
"Looked for, not found" drops any concept found in any run. Sources read are the union.

**Programmes.** The headline adds status and dates. Under the quote and source, `  - Label: value`
lines: Description, Themes, For (populations), Approach (lenses), Tagged from, and Where, Funded by,
Spend, Results — the place, partner, spend and metric findings whose `program_name` matches. Those
findings stay in their own sections too.

**Order.** Sections follow `entity-record` for the row's `entity_kind`; a section with nothing says
"Not recorded."

**Publish.** `save_research`, `publish_brief` and `make client-docs` render from all rows per slug.
The Storage key does not change.

**Frontend.** `parseBrief.ts` reads detail lines into `Finding.details`; `BriefArticle.tsx` lists
them with the existing `.brief-sources` class. No new class or token, so no design-system change.

## Milestones (one PR)

1. **Backend render.** `brief.py` merge, programme details, skill order; callers pass all rows.
   Exit: existing tests pass; the KABIL and Axis briefs rendered from staging show their programmes.
2. **Frontend.** Parser and article read detail lines. Exit: `npm run lint` and `npm run build` pass.
