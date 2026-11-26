# Import: Scout keeps the grants in a staff workbook

Part A of [#326](https://github.com/project-tech4dev/sangam/issues/326) (epic #332). **Draft v1, still being brainstormed**: no code until it is approved. Branch `docs/326-staff-workbook-grants`, off `master`.

## Context

Staff upload workbooks such as "FFRH NGOs Details of programs and current funders.xlsx" (document 25). Its
"CSO Funder Details" tab has 150 grants (funder → NGO, project, year, ₹), but Sangam kept 2 `funder_activity` lines,
with no amounts. The user wants the agent to read the file and keep the grants, adding a funder Sangam lacks.

Why only 2 survived (read in source):
1. **An NGO's grant line is held when its funder is unknown.** `promote_facts.py:276-292`: "an NGO's record never
   creates the funder … A person adds or links the funder first". About 25 of the file's 37 funders aren't in Sangam.
2. **The researcher prompt files a CSO-sheet grant under the funder** (`prompts/entity_researcher.md:22`, "a `partner`
   finding for the funder"), yet the run researches the NGOs in the file.
3. **Two funders' grants to one NGO collide.** The brief keys `partner` on `(partner_name, project_name,
   fiscal_year)` (`brief.py:187`). On an NGO's research `partner_name` is the NGO itself, so Caring Friends' and
   APPI's FY2022-23 grants to The ANT merge into one.
4. **Two projects from one funder in one year collapse.** On an NGO save, `_org_line(funder, org, fy)`
   (`promote_facts.py:~303-320`) finds the funder's one line for that NGO and year, adopts its `project_name`, and turns
   a different project into a `Conflict` instead of a second line.
5. **An NGO save shows no questions in Review.** `write_preview` (`catalog/save.py:130-132`) returns none for an org.

Decided with the user:
- The agent reads the file. Only grants are in scope; profile facts and partner relationships are out.
- **A new funder** is added from the row, and the grant saves without waiting. After the save, Scout lists the funders
  it added and the person ticks which to research.
- **An NGO Sangam already holds gets a sheet-only pass:** its rows, no web research. An NGO new to Sangam (Ajagar
  Social Circle) gets full research.
- **A near-match** ("APPI" vs Azim Premji Foundation) is a question on the Review & save card.
- **Two amounts disagree:** compare year and project first. A different year or project means separate lines. A
  range of years is one line, with the total noted. The same year and project with a different amount means looking
  elsewhere first; failing that, save the stronger figure and flag the other.

## Agent architecture (new parts marked ★)

```
person ── Sources card (choose_sources: ticks the workbook)
              │
        Scout supervisor (MODEL)
              │ 1. task(workbook-reader, documents)      ★ returns grantee NGOs and their funders separately
              │ 2. task(entity-researcher) per NGO, in waves
              │        ★ NGO already held (funder_dossier): sheet only, read_source_rows FIRST (closes web tools)
              │        new NGO: web research → read_source_rows LAST, as today
              │        ★ each grant row = one `partner` finding on the NGO's research, with funder_name
              │        ★ same-year conflicts, ranges, no-year rows handled by the prompt's rules
              │        save_research
              │ 3. Review & save (SaveQuestions → ReviewCard)
              │        ★ write_preview plans an NGO save too → asks "APPI = Azim Premji Foundation, or new?"
              │        promote_research → promote_facts partner branch
              │            ★ no match → placeholder funder (registry_status='placeholder'), grant line written
              │            ★ near match → the person's answer (reuses promote._answered)
              │ 4. ★ the save report carries funders_added; the Done screen lists them with tick boxes and
              │      "Research these", which sends Scout a message naming them (works for screen and chat saves)
              └─ 5. task(entity-researcher) per ticked funder → resolve_funder finds the placeholder by name → fills it
```

There are no new tools, subagents, tables or migrations. The changes are to rules, a fact key, a preview, and three
prompts.

## Milestones (one stacked PR each, in a worktree off master)

This document is committed on its own branch before any code.

### M1: the save path (backend, deterministic). PR "fix(import): keep a staff sheet's grants on an NGO's save (#326)"
- **`catalog/promote_facts.py` partner branch, `owner.column == "org_id"`.** When `resolve_funder(f.funder_name)`
  is not in `MERGEABLE`:
  - **Trigram candidates:** the answer goes through `promote._answered` (move it if R1/R3 require). `update`
    attaches the grant to that funder and adds the row's spelling as an alias. `new` creates the funder. No answer
    yet means the line is held, as today.
  - **No candidates and the finding is `source_type == "staff_dataset"`:** create a placeholder with
    `writer_funder.write_funder` (name, `registry_status='placeholder'`, provenance = the sheet's cell) and write the
    line. Web-sourced NGO findings keep today's hold; that's my call, to keep the change to staff data.
  - Record each created funder in `report["funders_added"]` (name and id). It persists in `entity_research.saved`
    like the rest of the report. Add the field to `PromotionReport` (`findings.py:275`, `extra="forbid"`).
- **`_org_line` matches on project too.** When the funder has no line for that NGO, year and project, write a new
  line rather than adopting another project's line. A line with no project still adopts the single line that has one,
  as today.
- **Cross-source amounts are already guarded:** `fill_only` with `PARTNER_GUARDED` (`writer_funder.py:335`) keeps a
  stored amount and records a `Conflict`. Pin that with one test, sheet ₹7 lakh against a stored ₹1.25 crore.
- **`brief.py:_SAME_FACT["partner"]`:** add `funder_name`, so two funders' grants to one NGO stay separate. A funder's
  own research leaves `funder_name` empty, so its keys are unchanged.
- **`catalog/save.py:write_preview`:** plan an org save with `Gate(plan=True)` as funders already are, so `questions`
  carries the partner-funder near-matches and `planned` counts the grant lines.
- **Same-key duplicates in one save** (same funder, year and project, different amount): write the stronger finding by
  `SOURCE_PRECEDENCE` then evidence tier, and add a `Conflict` holding the other amount. Reuse `writer.Conflict`;
  conflicts already reach `report["conflicts"]` and the Review card.
- **Docs:** `docs/ARCHITECTURE.md` §4 changes the rule "an NGO's record never creates the funder" to "a staff sheet's
  grant may add a placeholder funder; a near match is asked". Add a CHANGELOG line.
- **Tests** (`tests/test_promote_*` style, monkeypatched repositories, no DB):
  - an unknown funder on a staff row → placeholder plus line;
  - the same on a web row → held;
  - a trigram near-match → question, then `update` → line on the existing funder plus alias;
  - two funders, same NGO, same FY → two facts;
  - one funder, same NGO, same FY, two projects → two lines;
  - a sheet amount against a stored audit amount → stored kept, plus a conflict;
  - same key, two amounts → one line plus a conflict;
  - re-saving the same file → no duplicate lines (the unique key), no second placeholder (exact-name resolve).
- **Exit gate:** pytest, ruff, and codecov/patch green.

### M2: the agent (prompts). PR "feat(import): research a grants workbook NGO by NGO and offer its new funders (#326)"
- **`prompts/workbook_reader.md` and `research/findings.py:WorkbookEntity`:** the reader still returns no figures.
  For a sheet of grants it returns each grantee as `kind: org` and each funder as `kind: funder`, so the supervisor
  knows which to research first.
- **`instructions.md` ("everyone in a file"):** for a grants workbook, launch researchers for the NGOs. Check each
  NGO with `funder_dossier(name, "org")`, which is already on the supervisor's `TOOLS`:
  - **held:** the task says "sheet only". The researcher calls `read_source_rows` first, which closes its web tools,
    saves the grants, and marks every other field as a `not_reached` gap.
  - **new:** full research, as today.

  When the person asks to research funders added, run them in waves. When the list is longer than two waves, do two
  per turn and offer the rest, so each turn stays under 1800 s.
- **`prompts/entity_researcher.md` staff-sheet paragraph:** on an NGO's research, a CSO-sheet grant is a `partner`
  finding **on the NGO**, with `funder_name` as printed and the cell marker. Then the user's rules:
  - a different FY or project is a separate finding;
  - a range is one finding with `start_date`/`end_date` and the total quoted in evidence and `notes`;
  - the same FY and project with two amounts: check the web research already done (audit, annual report). If still
    unclear, save the figure from the row carrying year and project and name the other in `notes`;
  - a row with no year goes in `unplaced` with its marker, so Review shows it.
  - Update `skills/catalog-write-report/SKILL.md` to report funders added.
- **Tests:** the existing test asserting each subagent's tools are named in its own prompt; a test that
  `WorkbookEntity` still forbids figures.
- **Exit gate:** CI green. One local Import of the FFRH file on the **local DB**, never shared Supabase. Expected
  cost: 11 sheet-only Sonnet passes plus 1 full research, roughly $1–3 and about 10 minutes. Offer `make wiki-update`
  (paid) afterwards rather than running it.

### M3: the screen. PR "feat(import): Review asks about near-match funders and lists funders added (#326)"
- **`ReviewCard.tsx`:** render the partner-funder near-match questions, if the existing question renderer doesn't
  already fit them.
- **`DoneReport.tsx`:** read `funders_added` from the saved report and list them with tick boxes. "Research these"
  sends Scout a chat message naming the ticked funders. This covers the default screen save (`ScreenReview` →
  `POST /save`), where no agent sees the report. Styles go in classes, with Lucide icons.
- Run the design-system sync check, since Import is a UI-kit screen.
- **Exit gate:** Vitest plus `npm run build` green. Browser test as staff and as a steward, at desktop and phone width.

## Verification (end to end, local DB)
1. `make up && make seed`. Put the FFRH file in the `staff-sources-local` bucket so the Sources card lists it.
   `make staff-source` is staging-only (`Makefile:232`); choosing the file on the card registers its `documents` row.
2. In Scout, choose that workbook and ask "research every NGO in this file". Expect a wave of 12 NGO researchers.
3. Review & save:
   - **Questions:** "APPI" and "Child Aid Network Germany" are asked as near-matches.
   - **Planned:** about 150 grant lines minus no-year rows.
4. After saving:
   - `SELECT count(*) FROM funder_activity WHERE kind='partner' AND document_id=25` → about 140, not 2.
   - `SELECT count(*) FROM funders WHERE registry_status='placeholder'` → about 25.
   - Caring Friends → The ANT carries ₹1.25 crore with the ₹7 lakh in a conflict.
5. Re-run the same import and save → the counts are unchanged.
6. Tick two new funders → their research fills the placeholders, with no duplicate funder.

## Out of scope
- #326's other asks: profile facts, partner/technical-support relationships, consistency checks across sources, the
  `resolution_queue`, and relinking web-research mentions. A follow-up re-runs the FFRH import on Dev after Deploy.
- A deterministic column-mapping import. The user chose the agent reading the file.
