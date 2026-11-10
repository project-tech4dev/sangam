# Sangam Pitch fills in the funder's form

**Status:** Draft v2, 22 Oct 2026. For review; no code yet. v1 (21 Oct, same PR) made the form's headings the parts Sangam
writes. On review that was dropped: Sangam writes its own parts as today, then fills the funder's form at the end.
**Builds on:** `docs/features/2026-10-14-proposal-copilot.md` (live: steps 1–5, the polish check, the Word file and its
versions). Nothing in steps 1–4 changes.
**Branch:** `docs/pitch-form-outline`. The code lands as one PR per milestone, stacked.

---

## 1. Goals

**When the funder has its own form, Sangam Pitch takes the proposal it has already written and fills it into that form's
headings, as a Word file in the Doc Vault the person can edit and send.**

| Goal | Example | How we know it worked |
|---|---|---|
| **G1. The writing doesn't change.** | Asha, SeSTA's steward, goes through steps 1–4 as today. Sangam writes its usual parts from cited facts. | Steps 1–4 gain no code paths. Every existing proposal test passes unchanged. |
| **G2. The form's headings, in the form's order.** | Asha uploaded Redington's form in step 2. In step 5 she presses *Download in Redington's form* and gets a Word file headed "1. Executive Summary", "2. Introduction" … "14. Any other information". | The file's headings are the form's, numbered as the form numbers them. |
| **G3. Each answer comes from what Sangam wrote.** | "5. Proposed strategy" is Sangam's Objectives and Activities text, merged. "1. Executive Summary" is the Summary. | Code refuses any answer that adds a figure, place or name not already in the written parts. |
| **G4. The form's limits are kept.** | Redington allows 1,500 characters for the strategy. Objectives plus Activities run to 2,900, so the answer is cut to fit, and the screen says what was cut. | No answer is over its limit. Every cut claim is listed. |
| **G5. What Sangam can't answer is marked, not invented.** | SGP asks "7. Innovation". Nothing Sangam wrote covers it, so the answer is `[Add: innovative aspects of the project]`, highlighted. PAN number, budget table and CVs are `[You fill: …]`. | Every heading in the form appears in the file, answered or marked. |

**Not goals for this version:** keeping the funder's own layout, logo or tables (the file is new, with their headings),
drafting tables, pre-filling admin fields from the registry, or writing new text for a heading Sangam has no part for.
Each is in §8.

### What we learned from three real files

| File | Kind | What it means here |
|---|---|---|
| **Redington Foundation template** (8 pp) | Blank form | 14 numbered questions, most with a character limit (Executive summary ≤ 2,000, Introduction ≤ 500, Problem ≤ 3,000, Strategy ≤ 1,500, Timelines ≤ 300). Q3 is 19 short fields of 50–100 characters. Q12 is "Phase II applicants only". Most headings map onto one or two of Sangam's parts. |
| **GEF SGP OP8 template** (33 pp) | Blank form plus an application pack | Part 2's 8 prose questions map well onto Sangam's parts. About half the pack is fields (PAN, 12A, turnover), tables and annexes, which all become `[You fill]`. Annex 4 (terms and conditions) is skipped. |
| **SeSTA proposal** (6 pp) | A proposal SeSTA wrote | Its 19 headings work as a "form" too. Sections 1–11 are images, so the outline must be read from the PDF as images, not from pypdf's text. |

---

## 2. Blast radius

Built by hand from `CLAUDE.md`'s Architecture section and a grep of the step-5 path (`routes/proposals.py` `polish_language`
and `save_version`, `assemble.py`, `polish.py`, `FinishCard.tsx`). No table changes: everything is in `proposals.work`
(jsonb). `proposals` is not in the SQL catalog, so Ask Sangam can't see any of it.

| Surface | Hop | Why affected | Status | Notes |
|---|---|---|---|---|
| `proposals.work.template` | 0 | gains `outline` (the form read once, kept) | in scope | jsonb, no migration |
| `proposals.work.versions[]` | 0 | an entry gains `shape: "form"` and `report` | in scope | — |
| `app/proposals/form.py` | new | reads the form into an outline; pure check | in scope | §4.1 |
| `app/proposals/fill.py` | new | fits written parts into the headings; pure check | in scope | §4.2 |
| `prompts/form_reader.md`, `prompts/form_fill.md` | new | the two calls' instructions | in scope | — |
| `app/proposals/assemble.py` | 1 | a second Word layout: the form's headings | in scope | §4.3 |
| `api/routes/proposals.py` `save_version` | 1 | takes `shape: "form"` | in scope | no new route, §4.4 |
| `schemas/proposals.py` | 1 | request body and the version's `report` | in scope | — |
| `frontend/.../FinishCard.tsx`, `api.ts` | 2 | a second download button and the report | in scope | design system sync, §4.5 |
| Sangam Pitch prompt, `instructions.md` | 2 | the step 4–5 rule names the new button (rule 9 on master) | in scope, M2 | one line |
| Steps 1–4, readers, facts, `write_section`, questions | — | untouched | unaffected | G1 |
| `rubric.sections_for`'s `template.questions` | — | dead code: nothing saves `questions` | unaffected | §8 #5 |
| Ask Sangam, Import, Funder Match | — | no proposal code | unaffected | — |

---

## 3. High-level design (HLD)

### 3.1 Flow (new parts marked ★)

```
 Step 2: "Upload the funder's form" (exists) ─► Doc Vault ─► work.template {document_id}
 Steps 1–4: unchanged. Sangam writes its parts from cited facts.
 Step 5, "Before you send it":
   [Smooth the language]  [Download as a Word file]  ★[Download in Redington's form]
                                                          │  POST /versions {shape: "form"}
                                                          ▼
   ★ 1. outline: read once, kept in work.template.outline (RESEARCH_MODEL, the PDF as a document)
        T5 "5. Proposed strategy…" · prose · ≤ 1,500 chars · uses A4, A5
   ★ 2. fill: one call (MODEL) fits the written parts into each prose heading, in the style
   ★ 3. check (code): no new figure, place or name · within the limit · gaps kept
        a heading that fails ─► its parts as they are if they fit, else [Add: …]
   ★ 4. Word file: the form's numbered headings · answers · [You fill: …] · [Add: …] highlighted
        ─► Doc Vault as the next version, with what was cut and what is left for the person
```

### 3.2 The one rule

> **The rule:** filling the form may move, merge, shorten and drop what Sangam wrote. It may never add a figure,
> place or name.
> **Example:** Objectives says "2,400 women farmers in 22 villages" and Activities says "54 trainings". The strategy
> answer may keep both or drop "54 trainings" to fit 1,500 characters. If it says "2,500 women", code refuses that
> heading and puts in the two parts unchanged if they fit, or a gap if they don't.
> **Why it matters:** every claim in the funder's form then traces back to a fact the person checked in step 5.

This is `polish.differences` (`polish.py`, the check behind "Smooth the language"), with one change: a dropped claim is
allowed and reported, because a limit can force a cut.

### 3.3 What is touched

| | Touched? |
|---|---|
| Postgres | `proposals.work`, and one `documents` row per version (as today) |
| Supabase Storage | the uploaded form is read; the Word file is written (as today) |
| Model | two calls on the first fill (outline, then fill), one on later fills (the outline is kept) |
| Neo4j | no |
| New endpoint | none: `POST /api/proposals/{id}/versions` takes an optional body |

### 3.4 Trade-offs

| Choice | Chosen | Why |
|---|---|---|
| **When** to read the form | At the first fill, in step 5 | Steps 1–4 stay untouched (G1). The cost: the person only sees the form's shape at the end. |
| **A new Word file**, not their file filled in | New file | It works from a PDF or a Word upload and reuses `assemble.docx`. Filling their own `.docx` in place breaks on every layout (Redington's boxes, SGP's tables). Confirmed in conversation, 22 Oct. |
| Outline on **`RESEARCH_MODEL`** (Sonnet 5.5) | yes | Mapping "5. Proposed strategy" onto Objectives *and* Activities, and spotting "Annex 4: Terms" as skip, is judgment. Once per form: ~33 pages as images is about $0.25. |
| Fill on **`MODEL`** (Opus 5.5) | yes | Same tier as "Smooth the language", the nearest existing call. Merging and cutting to a limit without losing the strongest facts is the hard part. |
| **Unanswered heading → gap**, not new writing | gap | Writing fresh text for "Innovation" needs the step 3–4 writer and its fact checks. Later, §8 #2. |

---

## 4. Low-level design (LLD)

### 4.1 Reading the form: `app/proposals/form.py` (new)

```python
class Limit(BaseModel):
    n: int                                   # 1500
    unit: Literal["chars", "words", "pages"]

class Heading(BaseModel):
    number: str | None                       # "5", "3(b)", "Annex 3"
    label: str                               # "Proposed strategy to address the problem"
    ask: str                                 # the form's guidance under it, ≤ 1,000 chars
    kind: Literal["prose", "field", "table", "attach", "skip"]
    limit: Limit | None                      # None means none stated, never zero
    uses: list[str]                          # Sangam's part codes it draws on: ["A4", "A5"]; [] when none fits
    only_if: Literal["earlier_phase"] | None

class Outline(BaseModel):
    headings: list[Heading]                  # in the form's order
```

- `async read(doc, settings) -> Outline`:
  - **PDF:** sent as a LangChain file block (`{"type": "file", "base64": …, "mime_type": "application/pdf"}`), which
    `langchain-anthropic` 1.7.6 should turn into an Anthropic document block, so image pages are seen. **M1 proves this with
    a test first.** If the block doesn't get through `init_chat_model`, fall back to pypdf text and report that image pages
    were skipped.
  - **Word:** `python-docx` text, as `vault.read` already does.
  - `resolve_model(settings.research_model).with_structured_output(Outline)` with `prompts/form_reader.md`. The prompt
    carries Sangam's part list (code, label, question), substituted with `.replace()` like `{{TABLE_MAP}}`, and one example
    of each `kind` from the three sample files.
  - Over 100 pages or 32 MB (Anthropic's PDF limits): pages 1–100, and the report says so.
- `check(outline, codes) -> Outline` (pure):
  - drops a `uses` code that isn't one of this proposal's parts;
  - caps lengths;
  - turns a heading with no label into part of the one before;
  - gives each heading a code `T1`…`Tn`.
- **Kept** in `work.template.outline` with the `document_id` it came from. A new upload has a different id, so it is read again.

### 4.2 Filling: `app/proposals/fill.py` (new)

- `async fill(outline, written, style, model) -> dict[str, str]`: one structured call with `prompts/form_fill.md`.
  - **Input:** each prose heading (number, label, ask, limit), plus the text of the parts it `uses`, taken from
    `assemble.final(work)` (the smoothed wording where there is one), and the style.
  - **Output:** one answer per heading code.
  - **Prompt rules:** keep every claim you keep word for word; cut the weakest first; never add a number, place or name;
    keep every `[Add: …]` gap that falls in what you keep; answer `[Add: <the form's ask>]` when the parts don't cover it.
- `check(heading, sources, answer, districts, names) -> Checked` (pure). Built on `trace.extract`, as `polish.differences` is:
  - any claim in `answer` that isn't in `sources` → refused;
  - over `limit` (characters or words, counted on `assemble.plain`) → refused;
  - claims in `sources` but not in `answer` → **reported as cut**, not refused.
- `resolve(outline, written, answers) -> list[Filled]` applies the fallback per heading:

  | Case | What goes in the file |
  |---|---|
  | the answer passes the check | the answer |
  | refused, and its parts' text fits the limit | the parts' text, unchanged, one after another |
  | refused, and it doesn't fit | `[Add: <label>: Sangam's text runs to 2,900 characters; the form allows 1,500]` |
  | `uses` is empty, or none of its parts is written | `[Add: <the form's ask>]` |
  | `kind` field / table / attach | `[You fill: <label>: <ask>]` |
  | `kind` skip, or `only_if: earlier_phase` on a first phase | left out |

  It never blocks: a form always comes out, with marks where Sangam couldn't help.

### 4.3 The Word file: `app/proposals/assemble.py`

- `form_docx(title, byline, filled) -> bytes`: the same document setup as `docx`. Each heading is `"{number}. {label}"` at
  level 1. `[Add: …]` and `[You fill: …]` are highlighted, as gaps are today. ⟦k⟧ marks are stripped with `plain`.
- `content_md` for the `documents` row uses the form's headings too.

### 4.4 The route: `api/routes/proposals.py` `save_version`

- **Body:** `SaveVersionIn(shape: Literal["sangam", "form"] = "sangam")`. With no body, it behaves exactly as today (a test
  pins this).
- **`shape == "form"`:**
  - 409 "No funder form was uploaded in step 2" when `work.template` is empty or skipped.
  - Otherwise: outline (kept or read) → `fill` → `resolve` → `form_docx` → upload → `insert_draft` as today.
- **Version entry:** gains `shape` and `report: {cut: {T5: ["54 trainings"]}, add: ["T7"], you_fill: ["T12", "T13"]}`, so the
  card can say what happened. Its title reads "Version 3, in Redington's form".
- **Errors:** a failed outline read returns 502 "Sangam couldn't read the funder's form just now. Try again." A failed fill
  call drops every prose heading to its fallback rather than failing.
- `instructions.md`'s rule on the finish buttons (rule 9 on master) gains one line, with the button in M2: "When the funder's form was uploaded, a third button, *Download in the funder's
  form*, fills it from the written parts; point to it, never fill it in chat."

### 4.5 Screen: `FinishCard.tsx`, `api.ts`, `globals.css`

- **When `work.template` is set,** a third button: **Download in {funder}'s form**, next to *Download as a Word file*.
  While it runs: "Reading {funder}'s form and filling it in…". The first fill takes about a minute.
- **After it's saved,** a short report under the button, one line each:
  - "Cut to fit: 2 headings (open to see what was cut)"
  - "Left for you: 7 headings, marked [You fill] in the file"
  - "Sangam had nothing for: 7. Innovation, marked [Add]"
- **In the versions list,** a form version says "in Redington's form".
- **Styles:** new classes `.pr-report`, `.pr-report-row` in `globals.css`, from existing tokens only. **The design system is
  updated in the same PR**: the Pitch page in `ui_kits/sangam-web/`, per `docs/DESIGN_SYSTEM.md`. Icons from Lucide
  (`FileText`).

### 4.6 Step 2: say what the form is for, and catch one uploaded in the wrong place

> **The rule:** step 2 tells the truth about the form: it shapes the download, not the writing.
> **Example:** after Asha uploads Redington's form, the card says *"You uploaded it. Sangam writes its usual parts, and in
> the last step you can download them filled into this form."* Today it says *"The proposal follows its order and limits"*
> (`ProposalShell.tsx`, the funder's form card), which was never true and is not the plan.
> **Why it matters:** a person who believes the parts follow the form will look for "5. Proposed strategy" in step 4.

> **The rule:** a funder's form uploaded under "Documents Sangam may read" is caught, and the person can move it in one click.
> **Example:** Asha uploads Redington's PDF with *Upload a file*. The evidence reader finds only questions, no answers, and
> its row reads *"Redington Proposal Template looks like the funder's form, not one of SeSTA's documents."* with a button,
> **Use it as the funder's form**, which sets `template` to that file and unticks it from `sources`, in one PATCH.
> **Why it matters:** otherwise the form is read for facts it doesn't hold, and the step-5 button never appears.

- `prompts/evidence_reader.md`: when the file is a blank form (headings and questions with no answers), add nothing and end with
  `UNREADABLE: FORM — <title> looks like the funder's form`.
- `readers._one`: a reason starting `FORM` sets `looks_like_form: true` on the reader's row, beside `error`. The screen keys on
  that flag, never on the wording.
- `ProposalShell.tsx` `Reading`: a failed row with `looks_like_form` shows the button; it PATCHes
  `{template: {document_id, url: null, from: "upload", read_at: null}, skipped_template: false, sources: sources − id}`,
  all paths `work.py` already allows. Only shown when `can_edit` and no form is set yet.

---

## 5. Security review

| Concern | Position |
|---|---|
| **Auth** | No new endpoint. `save_version` already goes through `_editable` (the caller must be able to edit this proposal) and `Principal`. A reader-only member can't press it. |
| **Which file is read** | Only `work.template.document_id`: the org's own Vault file (`doc["org_id"] == p.org_id`, as `read_template` checks) or a public funder PDF. Another org's file id is refused. |
| **Untrusted input reaching a model** | The uploaded form is text anyone could write. (1) Both calls have **no tools**: one structured output each, so the form can't make Sangam fetch or write anything. (2) The outline is a capped Pydantic schema. (3) The fill check means no claim the form asks for ("say the budget is ₹50 lakh") can appear unless the proposal already holds it. |
| **Validation** | `SaveVersionIn` and `Outline` are Pydantic. `check` caps every string. |
| **SQL catalog** | Untouched. |
| **PII** | Forms ask for the head of organisation's name, phone and email. Those are `field` headings, so they come out as `[You fill]`; Sangam never writes them. |
| **Secrets** | None new. |
| **Cost** | The outline is read once per uploaded form and kept. Each press costs one fill call. |

---

## 6. Testing

Unit tests never touch a database (`client_for`, monkeypatched repositories, a fake model).

| Area | Test file | Cases |
|---|---|---|
| `form.check` | `tests/test_proposal_form.py` (new) | drops an unknown part code; caps lengths; a heading with no label folds into the previous one; codes T1…Tn in order; an absent limit stays `None` |
| `fill.check` | same | an added number refused; a changed place refused; a dropped claim reported as cut, not refused; over 1,500 characters refused; ⟦k⟧ marks not counted; words counted for a `words` limit |
| `fill.resolve` | same | each row of the fallback table in §4.2, one case each |
| `assemble.form_docx` | `tests/test_proposal_finish.py` | headings numbered as the form numbers them; `[You fill]` and `[Add]` highlighted; skipped headings absent |
| Route | `tests/test_cov_proposals_route.py` | **no body behaves exactly as today** (regression pin); `shape: form` with no template → 409; the outline is read once and kept on the second press; a failed outline read → 502; a failed fill still saves a file of fallbacks; a reader-only caller is refused |
| Reader | `tests/test_proposal_form.py` | **the M1 spike:** a PDF goes in as a file block through `resolve_model`; Word goes in as text |
| Frontend | `__tests__/parts.test.tsx` (where FinishCard is tested today) | the third button only with a template; the report lines; the version label |
| Eval (costs money) | `tests/evals/cases/golden.jsonl`, `TAG=pitch-form` | the three sample files' outlines, graded by code. Redington: "1. Executive Summary" ≤ 2,000 chars uses A1, heading 5 uses A4 and A5, Q12 is `only_if: earlier_phase`. SGP: Annex 4 is `skip`. SeSTA: headings 1–11 are found although they are images. The files stay outside the repo; the case reads a path from `PITCH_FORM_SAMPLES`. |

---

## 7. Milestones

One PR each, stacked. Each stops for review before the next.

#### Milestone 1: Fill the form, backend
- **Deliverable:** `POST /versions {shape: "form"}` saves a Word file in the funder's headings to the Doc Vault, with the report.
- **Touches:** backend, prompts.
- **Key tasks:**
  - [ ] Spike first: a test that a PDF file block gets through `resolve_model`.
  - [ ] `form.py` and `prompts/form_reader.md`.
  - [ ] `fill.py` and `prompts/form_fill.md`.
  - [ ] `assemble.form_docx`.
  - [ ] `save_version` body, `schemas/proposals.py`.
  - [ ] `work.apply` refuses an outline from anyone but `save_version`.
- **Acceptance:** `pytest tests/test_proposal_form.py tests/test_proposal_finish.py tests/test_cov_proposals_route.py` and
  `ruff check .`. By hand: the three sample files each give a Word file from a written proposal on staging.

#### Milestone 2: The button and the report
- **Deliverable:** step 5 has *Download in {funder}'s form*, the report, and the version label. Step 2 says what the form is
  for and catches one uploaded in the wrong place (§4.6). The design system is synced.
- **Touches:** frontend, design system, one reader prompt line.
- **Key tasks:**
  - [ ] `api.ts`.
  - [ ] `FinishCard.tsx`, and the `instructions.md` line naming its button.
  - [ ] Step 2 sentence; `looks_like_form` in `readers._one` and `evidence_reader.md`; the *Use it as the funder's form* button.
  - [ ] Classes in `globals.css`.
  - [ ] `ui_kits/sangam-web/` Pitch page.
- **Acceptance:** `npm run lint && npm test && npm run build`. In Chrome as a steward, as a reader-only member, and at phone
  width: upload Redington's form, write, and download it end to end.

#### Milestone 3: Eval and docs
- **Deliverable:** `make evals TAG=pitch-form` runs the three files. ARCHITECTURE.md has the "filling never adds a claim" rule.
- **Touches:** evals, docs.
- **Key tasks:**
  - [ ] Eval cases.
  - [ ] ARCHITECTURE.md.
  - [ ] CHANGELOG line.
  - [ ] `make wiki-update`.
- **Acceptance:** `make evals TAG=pitch-form` passes.

---

## 8. Open questions and risks

| # | Question or risk | Proposed answer |
|---|---|---|
| 1 | **The person sees the form's shape only at the end.** A heading like "Innovation" that Sangam never wrote shows up as `[Add]` in step 5, after the writing is done. | Accepted for v1: the report names it, and they write it in the Word file. Later: read the outline in step 2 and list its uncovered headings as a warning there. |
| 2 | **Uncovered headings stay gaps.** | Later: write them from the fact list with the step 3–4 writer and its cite check. |
| 3 | **Tables** (SGP Table 1 logframe, Table 3 budget) are `[You fill]`. | Later: a table answer whose cells cite facts. |
| 4 | **Admin fields** (PAN, Darpan ID, year registered) are often in the registry. | Later: pre-fill a `field` from the org record, still marked for the person to check. |
| 5 | **Dead code:** `rubric.sections_for` adds `template.questions` as parts, but nothing saves `questions`. | Left alone here. A one-line cleanup PR can remove it. |
| 6 | **The PDF file block may not get through `init_chat_model`.** | M1's first task is that test. The fallback is pypdf text, which loses image-only pages (SeSTA's sections 1–11). |
| 7 | **Redington Q3's 19 short fields** each have their own limit. Filling all 19 from Context and target area may leave many as `[Add]`. | Acceptable: they're separate headings in the form, and each one Sangam can't fit is marked. |
| 8 | **Proposal work not yet on master** (`feat/proposal-make-case`: two local commits plus uncommitted edits) touches `routes/proposals.py`, `schemas/proposals.py` and `ProposalShell.tsx`. | Checked 22 Oct: it doesn't touch `save_version`, `assemble.py` or the new files. M1 is built on master and rebased onto it when it lands; the overlap is imports and a neighbouring route. M2 touches `ProposalShell.tsx` too, so M2 waits for it. |
