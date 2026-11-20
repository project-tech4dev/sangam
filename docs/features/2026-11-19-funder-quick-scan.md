# Funder quick scan: Ask hands off to Scout when a funder is not in Sangam

Draft v1, 2026-11-19. Nothing built yet.

## 1. Goal

**When Ask is asked how an organisation fits a funder Sangam does not hold, it offers a quick scan in Scout.
The scan saves that funder with only theme, geography and eligibility, and Ask's `compare_fit` then scores it.**

Success: Asha (a steward of KABIL) asks "How does KABIL fit Azim Premji Foundation?" in Ask. Today she gets
"no funder found". After this change she gets a link, and the quick scan finishes in Scout in a few minutes.
Asked again, Ask answers "62/100, judged on 70 of 100 points, quick scan". A full Scout run on the same
funder later fills the remaining criteria, and the "quick scan" label goes away.

Decided in conversation (2026-11-19):
- The handoff is a link from Ask to Scout (approach A). Ask gets no web tool and no seventh tool.
- The scan's result is saved.
- A quick scan stays `registry_status = 'placeholder'`. A full research run moves the funder to `in_vetting`.
- Members see quick-scanned funders everywhere, labelled "Quick scan".

## 2. Blast radius

I built this by hand from `catalog.py`, the Architecture section of `CLAUDE.md` and the two explore reports.

| surface | hop | why affected | status |
|---|---|---|---|
| `EntityResearch` + `unanswered()` (`ingest/research/findings.py:72`, `contract.py:21`) | 1 | a scan must answer only 3 concepts | in scope |
| researcher skills (`ingest/skills/research/`) | 1 | new `funder-quick-scan/SKILL.md` | in scope |
| supervisor prompt (`ingest/instructions.md`) | 1 | how to dispatch a scan, then offer the full run | in scope |
| `write_funder` (`ingest/catalog/writer_funder.py:96-119`) | 1 | status by depth: insert or upgrade | in scope |
| `funders.registry_status` data | 1 | today every Import-made funder is `placeholder` | in scope (migration 0058) |
| `orgs.registry_status` (`writer_org.py:101`) | 1 | same hard-coded `placeholder` | deferred: there is no org scan, so nothing needs to tell them apart |
| `repositories/matching.py::_funders` + `FunderProfile` | 1 | carries `registry_status` | in scope |
| `compare_fit` output (`ask/tools/matching_tools.py`, `matching/match.py`) | 2 | adds a "quick scan" card line | in scope |
| Ask skills `funder-comparison`, `funder-matching` + `instructions.md` rule 13 | 1 | the not-found path offers the link | in scope |
| Scout screen (`frontend/features/ingest/ScoutChat.tsx`, `lib/composePrompt.ts`) | 2 | reads `?scan=<funder>&org=<org>` to prefill | in scope |
| Ask answer links (`features/ask/components/AnswerCard.tsx:37-60`) | 2 | `/import?...` opens in a new tab today | in scope (same-tab for internal links) |
| Funder Match page and saved runs (`matching/service.py`, `funder_matches.py:84`) | 2 | quick-scan funders appear in runs | in scope: label only, not excluded |
| Registry list and funder profile | 2 | members see placeholders (RLS `0027_rls.sql:75`) | in scope: "Quick scan" chip |
| SQL catalog note (`catalog.py:360,673`) | 1 | the note's meaning of `placeholder` changes | in scope: one-line note edit |
| Neo4j graph | — | built from Postgres and reads no status | unaffected |
| `make match` | 2 | already scores every funder | unaffected: the label covers it |

## 3. High-level design (HLD)

```
 Ask Sangam (Opus, no web)                         Sangam Scout (Import)
 ─────────────────────────                         ─────────────────────────────────────────
 "KABIL vs Azim Premji?"                            /import?scan=Azim+Premji+Foundation&org=kabil
   db_query: no funder by that name                   composer prefilled:
   → "Not in Sangam yet.                              "Quick scan funder Azim Premji Foundation for KABIL"
      [Quick-scan it in Scout](/import?scan=..)"      choose_sources (person ticks sources)
          │ (staff and stewards only;                  supervisor ─task→ entity-researcher        ★ NEW skill:
          │  anyone else is sent back to /ask)                          reads funder-quick-scan      funder-quick-scan
          └──────────────── link ──────────────────▶                   save_research(depth="scan")  ★ contract: 3 concepts
                                                       supervisor offers "Save?" → catalog-writer
                                                         promote → write_funder                      ★ status by depth
                                                           insert: placeholder
                                                       supervisor offers "Run full research?"
 asked again:                                          (later) full run: depth="full"
   compare_fit → FunderProfile.registry_status           write_funder: placeholder → in_vetting      ★
   card line "quick scan: 3 of 7 criteria researched" ★
```

- **Postgres:** `funders.registry_status` changes meaning, and a one-off migration moves the existing rows.
- **Model:** no new model calls. A scan is one researcher on `RESEARCH_MODEL` with a short contract.
- **Neo4j and Storage:** untouched.
- **Key trade-off:** the scan reuses Scout's researcher and writer rather than building a lighter path.
  - Cost: the scan pays for Scout's middleware and the sources step.
  - Gain: every saved field still carries a citation, and the score is still calculated in code.

> **The rule:** depth decides the status only on the way up. A scan never downgrades a funder.
> **Example:** Tata Trusts is `in_vetting` from a full run in October. A scan of it in November leaves it
> `in_vetting`.
> **Why it matters:** a quick scan must not hide research that was already done.

## 4. Low-level design (LLD)

**Contract (backend/app/ingest/research/)**
- `findings.py`: add `depth: Literal["full", "scan"] = "full"` to `EntityResearch`.
- `contract.py::unanswered`: when `depth == "scan"`, check only three concepts:
  - `identity`, with only `funder_type`, `section_135_bound` and `themes` required (eligibility scoring
    needs the first two, `rules.py:318-321`)
  - `stated_geography`
  - `eligibility_guideline`

  Put the set in `expectations.py` as `SCAN_CONCEPTS`, next to `concepts_for`. A scan with `entity_kind="org"`
  is refused. There is no org scan.
- `save_research` (`tools/research_tools.py:340`): no change to the signature. `depth` travels inside
  `findings` and is stored in `entity_research` with the brief.

**Skill:** `backend/app/ingest/skills/research/funder-quick-scan/SKILL.md`
- Three short sections lifted from `funder-intake-research`: §1 Identity (type, Section 135, themes), §5
  Footprint and priorities (`stated_geography` only), and §8 Eligibility (`eligibility_guideline`, no `rfp`).
- It uses the same source order and gap rules, says "set `depth: scan`", and caps reading at about 6 pages.
- `entity_researcher.md` gains one line: if the task says "quick scan", read `funder-quick-scan`, not the
  intake skill.

**Supervisor (`backend/app/ingest/instructions.md`)**
- A request that starts "Quick scan funder <name>" dispatches one researcher whose description says
  "<name> — quick scan".
- Next it offers to save, through the existing catalog-writer flow. The person still approves.
- Then it offers a full research run. The person makes every choice.

**Writer (`backend/app/ingest/catalog/writer_funder.py`)**
- `write_funder(..., depth)` comes from `promote.py:265`, which reads `depth` off the brief.
- Insert: `'placeholder'` if depth is scan, otherwise `'in_vetting'`.
- Update: if depth is full and the row is `placeholder`, add `registry_status = 'in_vetting'` to the SET.

**Migration:** `db/migrations/0058_funder_status_after_research.sql`

```sql
UPDATE funders SET registry_status = 'in_vetting' WHERE registry_status = 'placeholder';
```

It is safe because only `write_funder` ever wrote `placeholder`, and only after a full run. No seed writes it.
- Update `catalog.py:360,673` notes: "'placeholder' is a quick scan: theme, geography and eligibility only".

**Matching (backend/app/repositories/matching.py, matching/)**
- `_funders` also selects `registry_status`, and `FunderProfile.registry_status: str` is added.
- `match.py` adds the card line `quick scan: theme, geography and eligibility researched; the rest not yet`
  when the status is `placeholder`.
- `matching_tools.py` passes the line through. Saved runs store `match()` as it is, so the label lands in
  `funder_matches` with no schema change.

**Ask (prompt and skills, no new tool)**
- `ask/skills/funder-comparison/SKILL.md` §1 and `funder-matching/SKILL.md`: when a named funder has no row,
  say "not in Sangam yet" and give `[Quick-scan it in Scout](/import?scan=<url-encoded name>&org=<org slug>)`.
  - Add: "Scout is for Sangam staff and stewards; anyone else can ask them to run it."
  - Never judge the funder without it.
- `instructions.md` rule 13: one sentence that names the link.
- Rule 15: a "quick scan" line is repeated, and the score is read as judged on fewer criteria.
- A `test_instructions` assertion that the link pattern appears.

**Frontend**
- `features/ingest/lib/composePrompt.ts`: `scanLeadIn(funder, org)` → "Quick scan funder <funder> for <org>".
- `ScoutChat.tsx`: on mount, read `scan`/`org` from `useSearchParams`. Then select the `funder` task and set
  the draft. Nothing is sent: the person still ticks sources and presses send.
- `AnswerCard.tsx`: a link starting with `/` renders as `next/link` in the same tab. External links keep
  `target="_blank"`.
- Funder Match card and Registry card/profile: a "Quick scan" chip when `registry_status === 'placeholder'`.
  - Reuse the existing chip class, so no new token.
  - Add `registry_status` to the funder types in `lib/api/types.ts` and the two schemas that return it
    (`schemas/registry.py`, `schemas/funder_matches.py`).
- Design system sync: the Registry and Match screens are in the UI kit, so update the "Quick scan" chip in
  "Sangam Design System v2" in M3.

## 5. Security review

- **No new endpoint and no new tool.** Ask still has six tools and no web access, so the `fetch_url`
  data-leak risk stays closed.
- **Scout access is unchanged.**
  - `require_scout` gates the `/ingest` route.
  - `/import` redirects non-Scout users.
  - The prefill only types into the composer and sends nothing.
- **Query parameters are untrusted text.**
  - They go into the composer as plain text, never into HTML.
  - Length is capped at 120 characters.
  - The person reads it before sending.
  - Example: `?scan=<script>` shows as literal text in a textarea.
- **No catalog change.** `registry_status` is already in the SQL catalog. Members already see placeholders
  (`0027_rls.sql:75`); only the label is new.
- **No PII.** A funder is an organisation. Eligibility text is public.

## 6. Testing

Unit tests touch no database.
- `test_contract.py`: a scan with the 3 concepts passes, and a scan missing `stated_geography` is refused.
  A full save is unchanged. An org scan is refused.
- `test_writer_funder.py`:
  - scan insert → placeholder; full insert → in_vetting
  - full update of a placeholder → in_vetting
  - scan update of an in_vetting funder → unchanged (the "never downgrade" rule)
- `test_matching_*.py`:
  - A placeholder `FunderProfile` gets the quick-scan line, and an `in_vetting` one does not.
  - Score with only theme, geography, eligibility and relationship known: `judged_max == 70`.
  - Relationship is never unknown (`rules.py:353`), so 70 is the denominator, not 60.
- Ask: the instructions test checks that the link pattern is in the funder-comparison skill.
- Frontend Vitest:
  - `scanLeadIn`
  - `ScoutChat` prefills from `?scan=` and does not send
  - `AnswerCard` renders `/import?..` same-tab and `https://..` in a new tab
  - the chip shows for placeholder
- Integration: `test_migration_integrity.py` covers 0058.
- Eval: one `TAG=import` canary, "Quick scan funder Azim Premji Foundation for KABIL". It costs money and is
  run by hand.

## 7. Milestones

These are stacked PRs. Stop for review after each one.

#### Milestone 1: scan depth and status on the way up (backend, db)
- **Deliverable**: a scan saves 3 concepts and lands as `placeholder`. A full run lands as, or upgrades to,
  `in_vetting`. Existing placeholders are moved.
- **Touches**: backend, db, prompt (researcher)
- **Key tasks**:
  - [ ] `depth`, `SCAN_CONCEPTS`, `unanswered`
  - [ ] `funder-quick-scan` skill and the researcher prompt line
  - [ ] supervisor wording
  - [ ] `write_funder` by depth
  - [ ] 0058, catalog note
  - [ ] tests
- **Acceptance**:
  - `cd backend && pytest tests/test_contract.py tests/test_writer_funder.py && make migrate`
  - In Scout on the local DB: "Quick scan funder Azim Premji Foundation", save. Then
    `select registry_status from funders where name ilike 'azim%'` returns `placeholder`.

#### Milestone 2: compare_fit labels a quick scan, and Ask offers the link (backend, prompt)
- **Deliverable**: Ask scores a placeholder with the label, and a missing funder gets the Scout link.
- **Touches**: backend, prompt
- **Key tasks**:
  - [ ] `registry_status` on `FunderProfile`
  - [ ] card line
  - [ ] two Ask skills and rules 13 and 15
  - [ ] tests
- **Acceptance**:
  - `pytest -k "matching or instructions"`
  - In local Ask, "How does KABIL fit Azim Premji Foundation?" shows the label after M1's scan, or the link
    before it.

#### Milestone 3: the handoff and the label on screen (frontend, design system)
- **Deliverable**: the link opens Scout with the composer filled, and the chip shows on Match and Registry.
- **Touches**: frontend, two schemas, design system
- **Key tasks**:
  - [ ] `scanLeadIn`
  - [ ] `ScoutChat` prefill
  - [ ] same-tab internal links
  - [ ] chip
  - [ ] types
  - [ ] Vitest
  - [ ] design system update
- **Acceptance**:
  - `cd frontend && npm test && npm run lint && npm run build`
  - Chrome test as staff, steward and member, and at phone width. The member is sent back to `/ask`.

## 8. Open questions and risks

- **A score on 70 points can read high.** Example: theme met and Assam shared gives 62 out of 70, and the tier
  is computed on that. The label is the only guard. If staff misread it, the next step is to cap the tier at
  "medium" for placeholders. That is a one-line change in `rubric.py`, left out for now.
- **Org admins can run `compare_fit` but not Scout.** They get the link and are sent back to `/ask`. The skill
  wording tells them to ask staff or a steward.
- **Same-day upsert.** `entity_research` is keyed on (slug, date). A full run after a scan on the same day has
  more findings, so it replaces the scan. A scan after a full run the same day is refused, which is correct.
- **0058 assumes** every current `placeholder` came from a full Import. Check this on staging before
  `make migrate ENV=staging` with `select count(*), min(created_at) from funders where registry_status='placeholder'`.
- `make wiki-update` is offered after M3. It is not run as part of the PR, because it costs money.
