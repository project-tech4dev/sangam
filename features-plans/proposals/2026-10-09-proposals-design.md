# Proposals: design

*Proposed 9 Oct 2026. The UI was agreed on the same clickable prototype as Funder Match:
https://claude.ai/artifact/H1b4nv5ReQn8mvHg2HhPB5 (version 20). The prototype's data is invented, and its
section scoring is a keyword mock. Depends on the Funder Match spec (#126), which is not merged yet.*

## What it is for

An organisation's people write a funding proposal to one funder with Sangam doing the first draft.
Sangam drafts every section from what it already holds, and from what the organisation adds. The
person checks, edits and marks each section Done. The result is a clean .docx in the Doc Vault that
they can tweak and finalise. The **Proposal Writing Rubric v2** judges every section, so "ready to
send" means the same thing for every proposal.

It is reached two ways:
- **Start a proposal** / **Continue proposal** on a Funder Match card;
- **Proposals**, a new item under **Use Cases** in the Ask workspace sidebar, after Funder Match.

**Several proposals to one funder.** An organisation can be funded by the same funder for different
programmes, so it can have any number of proposals to one funder. Each is named for its programme.
This refines the Funder Match card (#126):
- no proposal to that funder: terracotta **Start a proposal**;
- one: sage **Continue proposal**, which opens it, with a small **Start another** link beside it;
- more than one: sage **Proposals (N)**, which opens the Proposals list filtered to that funder, with
  **Start another**.

Starting one asks for its name, prefilled "<organisation>: proposal to <funder>", for the person to
replace with the programme ("SeSTA: women's farm enterprises, Baksa"). The name is editable later in
the proposal's header.

**Out of scope**
- **Remembering gate answers across proposals** ("Remember these for next time"). Shown in the
  prototype as v2.
- **Several people editing one section at the same moment.** Edits to different sections never clash
  (see *Saving*); two people typing in the same section get a reload, not a merge.
- **Budgets as spreadsheets.** The budget is a section of text (A15). A budget workbook can be
  uploaded as a source document, but Sangam does not build one.
- **Submitting** to the funder, and the statuses after `drafting`. The existing `status` column keeps
  them for later.

## Who sees what

The same people as Funder Match, from sign-in: an organisation's members, admins and stewards, and
Sangam staff. **Everyone shown an organisation can start, edit and assemble its proposals**, stewards
included. That is a change to today's rules, where a steward only reads (see *Access*).

## The rubric, and how the page shows it

The rubric is kept **in code** (`backend/app/proposals/rubric.py`, `RUBRIC_VERSION = "proposal-v2"`),
like Funder Match's. Its parts, as used here:

- **Part A, 16 core sections** (A1 Summary … A16 Other funding). Each has a question, its Strong
  elements, and what Weak looks like. Each is scored 0, 1 or 2; the core score is out of 32.
- **This funder's sections**:
  - **F1 Fit with funder priorities**, always;
  - **F4 Earlier phase results**, only when the organisation has a past partner line with this
    funder (`funder_activity`) or the template asks about an earlier phase;
  - **one section per template question** that no core section covers, coded `T1`, `T2`… in storage.
- **Gates**: only **G1 Eligibility** and **G2 Documents**, ticked by the organisation. G3 and G4 are
  dropped.
- **Format overlays** from the template: a character or word limit on a section, or a required form
  ("a table by quarter").
- **Ready** when: both gates are ticked, no core section scores 0, A6, A15 and F1 score 2, and every
  overlay is met.

**Display codes.** Storage uses the rubric's codes. The page groups them so the list looks shorter:
A1–A7 (the case and the plan), B1–B5 for A8–A12 (people), C1–C4 for A13–A16 (durability and money),
and F1, F2, F3… for the funder's sections in order (F1, then F4 if present, then T1, T2…). The mapping
is one function in the frontend.

**The rubric lives in one place.** `GET /api/proposals/{id}` returns this proposal's rubric (sections,
questions, Strong elements, overlays, order) alongside `work`, and every save returns the new
`summary`. The page shows scores and readiness from those; it computes none itself, only the display
codes.

## The page: three steps

A stepper across the top: **1 Eligibility gates**, **2 Template, documents and style**, **3 Proposal**.
Each step can be reopened at any time. Step 3 is locked until steps 1 and 2 are done.

### Step 1: Eligibility gates

G1 and G2, each with the funder's requirement and what Sangam holds against it, cited ("On record:
12A, 80G, registered 2009 [org:3]. Not on record: CSR Form 1."). The person ticks each as met. There is
no pass or fail verdict from Sangam, because its data is rarely complete. **Continue** moves to step 2.

### Step 2: Template, documents and writing style

- **Funder template.**
  - When Sangam holds the funder's template (a `documents` row, `doc_type 'proposal_template'`, for
    this funder), its link is **prefilled in an editable box**, noting where it came from and when it
    was read. The person can change it (**Update link**), **Upload instead**, or **Skip: use standard
    sections**.
  - When Sangam has none, the box is empty, with the same three choices.
  - An uploaded template is saved to the Doc Vault.
  - Sangam reads the template once it is set. Its section order, limits and forms become overlays; its
    questions that no core section covers become T sections.
- **Your documents.** Annual reports, workplans, monitoring sheets, budgets, past proposals. Each
  upload goes to the organisation's Doc Vault through the existing upload routes and becomes a source
  for drafting. The block says how many of the organisation's documents Sangam already holds.
- **Writing style.** A default the person can rewrite for this proposal:
  > Plain, specific English for a CSR programme officer who reads many proposals. Short sentences,
  > active voice, third person ("SeSTA will…"). Open each section with its strongest fact or number.
  > Name places, groups and dates; no jargon, slogans or superlatives. Money in ₹ with lakh and crore;
  > every figure with its source and year.
- **Draft the proposal →**, inactive until step 1 is done. It drafts every section and opens step 3.

### Step 3: Proposal

- **Tabs across the top**, one per group, each with its score so far: The case and the plan, People,
  Durability and money, This funder.
- **A left sidebar** listing the tab's sections (A1, A2…) with a dot for each section's score and a ✓
  for Done.
- **The section**, in the middle:
  - its question, and the overlay if any ("Up to 2,000 characters");
  - **Drafted from**: chips for each source used (Sangam's records, a document, public data,
    reference figures, the knowledge graph);
  - **one text box** holding the draft. Anything Sangam could not find is left in the text as
    `[Add: …]`, naming what is missing, for the person to fill in;
  - which Strong elements the text covers, the character count, "N to add", the score, **Done** and
    **Next**.
  - **F1** opens with a short blurb on the funder's priorities: themes, places (aspirational districts,
    focus states) and eligibility rules, cited.
- **Suggestions from new documents** (see *Adding a document after drafting*): a card on each
  section that has one, with **Add** and **Dismiss**; the sidebar shows a count.
- **A ready line** at the foot: core score out of 32, the funder sections' score, overlays met,
  sections Done, Ready or what is missing, and **Assemble document**.
- **Saved as you go**: "All changes saved · just now" after every change.

**Assemble document** opens the assemble view:
- **As entered:** everything entered, section by section, exactly as written, with section codes and
  gaps shown as "Still needed: …". Its one action is **Polish with Sangam**.
- **Polish with Sangam** rewrites the whole proposal in one pass (see *The document*). Polishing is
  allowed while gaps remain; they stay marked.
- **After polishing:** a **Polished / As entered** toggle, **Polish again**, **.docx** and **Save to
  Doc Vault**, which stores the polished text as a new version. The polished text is read-only:
  changes are made in the sections, then polished again.
- If a section changes after a polish, a banner says "Sections have changed since this polish", with
  **Polish again**.

Versions are listed with date and who made them; each opens or downloads.

### The Proposals list

One row per proposal for the organisations the person can see: its name, organisation → funder, started on,
the fit score from the latest match, "N of M sections done · core 24/32", and Ready or not. Clicking
opens the proposal at the step it was left on. Empty state: "No proposals yet. Start one from a funder
in Funder Match."

The page follows CLAUDE.md: classes in `globals.css` with no inline styles, Lucide icons via `.icon`,
Title Case sidebar labels, and the same PR updates the design system with a `Proposal` page in
`ui_kits/sangam-web/`.

## Drafting

**When.** On **Draft the proposal →**, every section is drafted; the page shows each one as it
arrives. A single section can be redrafted later from its own menu.

**From what.** Each section request builds the *source pack* it needs: the organisation and funder
rows (cheap reads) and a search for that section's passages. It is read through the caller's own
connection (the repositories behind `PoolDep`), so row-level security decides what is
in it:

| Source | What it gives | Marker |
|---|---|---|
| The organisation's records | profile, locations, programmes, credentials, people | `[org:N]` |
| Funder activity | past partner lines, with this funder and others (A11, F4) | `[activity:N]` |
| The funder | themes, places, eligibility, CSR spend (F1, gates) | `[funder:N]` |
| Doc Vault documents | the organisation's documents, including those added in step 2; passages found by search over `chunks` | `[doc:N]` |
| Reference figures | district and state indicators, unit costs, norms (A2, A3, A15) | `[ref:N]` |
| The knowledge graph | relationships, when the graph is enabled; skipped cleanly when not | `[graph:x]` |

`[doc:N]` and `[ref:N]` are new markers, used only inside proposals; Ask Sangam's set is unchanged.

**Never through Ask's SQL tools.** `db_query` runs as the database owner until #114 is fixed. Drafting
uses named repository functions running as the caller.

**How.** One model call per section, given the section's question, Strong elements, overlay, the
writing style, the template's wording for it, and the source pack's passages for that section. It
returns:

```json
{"text": "…", "sources": ["org:3", "doc:41"], "missing": ["Mid-term and final evaluation"]}
```

Every Strong element it could not support becomes an `[Add: …]` in the text and an entry in
`missing`. The draft's score comes from `missing` in code: none missing is 2, one is 1, more is 0.

**Checking after edits.** When a section is marked **Done**, and for any section whose text has
changed since its last check when **Assemble** is pressed, one cheap model call judges the text
against the Strong elements and the overlay's form, and returns `{covered: […], missing: […]}`. The
score follows the same rule. A check is skipped if the text's hash has not changed. Character and
word limits are counted in code, not by the model.

**Funder and template reading.** Two more calls, run when the proposal starts and when the template
changes:
- **The funder brief:** from the funder's record and its `funder_eligibility` document, the F1
  priorities blurb and the G1/G2 requirements.
- **The template:** from its text, the section order, limits, required forms and questions, matched
  to rubric sections; the unmatched questions become T sections.

**Models.** Drafting uses `Settings.model`. Checks, the funder brief, template reading and
suggestions use `Settings.utility_model` (which falls back to `model`). No new setting. Every call is
traced in Langfuse as for the agents.

**Concurrency.** Sections are drafted in parallel, bounded by a small fixed number (4), from the
browser: one request per section. That keeps each request short and lets the page fill in as sections
arrive. `backend/vercel.json` sets no `maxDuration`; confirm the deployment's default covers the
slowest single call (a template fetch and read, or one section draft) and set it there if not.

**An interrupted draft.** Step 3 opens as soon as drafting starts; sections still being written show
"Drafting…". If the tab closes half way, the sections with no text are drafted again when the
proposal is reopened, and any that fail show **Draft this section**.

## Adding a document after drafting

When a document is added in step 2 after the proposal has been drafted, Sangam **suggests**
additions and the person accepts each one. It never changes text by itself.

1. The upload is recorded in the Doc Vault as usual.
2. One `utility_model` call takes the document's text and every section's current text, and returns
   only facts the sections do not already contain, each tied to a section:
   ```json
   [{"section": "A11", "text": "In 2021–24 SeSTA ran …", "source": "doc:57"}]
   ```
3. They are stored in `work.suggestions`. Each section with one shows a card, "From annual-report.pdf:
   …", with **Add** (appends the text to the section and marks the section unchecked) and **Dismiss**.
4. A suggestion survives edits to its section; the person decides.

Suggestions apply to Done sections too: adding one clears that section's Done.

## Data model

**At a glance.** No new tables. `proposals` gains `work` (everything the page edits) and `summary`
(what the list shows); `documents` holds the template, the organisation's uploads and each saved .docx.

```json
{
  "step": 3,
  "gates": {"G1": true, "G2": true},
  "funder": {"themes": ["Rural livelihoods"], "places": ["Baksa", "Udalguri"]},
  "template": {"url": "https://…/proposal-format.pdf", "order": ["A1", "A2", "T1"]},
  "docs": [57, 58],
  "style": "Plain, specific English …",
  "sections": {
    "A3": {"text": "In Tamulpur block, 38% of households … [Add: the cause]", "score": 1, "done": false}
  },
  "suggestions": [{"section": "A11", "text": "In 2021–24 SeSTA ran …", "source": "doc:57"}],
  "polished": {"A3": "Smallholder families in these villages go short of food …"},
  "versions": [{"n": 1, "document_id": 71, "at": "2026-10-09"}]
}
```
```json
{"done": 9, "total": 19, "core": 24, "ready": false}
```

The full shapes follow.


Light on purpose: **no new tables.** The proposal's work in progress is one JSON field, read and
written whole by one page, never queried piece by piece.

```sql
-- 0036_proposal_work.sql
ALTER TABLE proposals
  ADD COLUMN work    jsonb NOT NULL DEFAULT '{}'::jsonb,  -- everything the page edits, see below
  ADD COLUMN summary jsonb NOT NULL DEFAULT '{}'::jsonb;  -- what the list shows, computed from work on save

-- No uniqueness on (org_id, funder_id): one funder can fund several of an organisation's programmes.
-- The existing proposals_org_idx (org_id, status) serves the list.
```

Existing columns used as they are: `org_id`, `funder_id`, `title` (the programme name), `status` (`drafting`),
`template_id` (the template's `documents` row, when one is used), `draft_document_id` (the latest
assembled version), `created_by`, `created_at`, `updated_at`. The match is found by `org_id` and
`funder_id` in `funder_matches`; `fit_score_id` is not used and is dropped with the fit-score tables
(#126).

### `work`, worked through

SeSTA → Axis Bank Foundation, part way through step 3. Values invented, shortened to two sections.

```json
{
  "rubric_version": "proposal-v2",
  "step": 3,
  "gates": {"G1": true, "G2": true},
  "funder": {
    "brief": {
      "themes": ["Rural livelihoods", "Women's collectives and SHG federations"],
      "places": ["North-East India", "Aspirational districts, including Baksa and Udalguri"],
      "eligibility": ["Registered 3 years or more; 12A, 80G and CSR Form 1", "Grants of ₹1–5 crore over 3 years"],
      "cites": ["funder:12", "doc:63"]
    },
    "gates": {
      "G1": {"rule": "12A, 80G and CSR Form 1; three years' standing",
             "on_record": "12A, 80G, registered 2009 [org:3]. Not on record: CSR Form 1."},
      "G2": {"rule": "CSR-1 certificate, audited accounts for three years, annual report",
             "on_record": "Audited accounts FY 2023-24 and 2024-25, annual report 2024-25 [doc:41]."}
    },
    "earlier_phase": false,
    "read_at": "2026-10-09T10:02:00Z"
  },
  "template": {
    "document_id": 63, "url": "https://www.axisbankfoundation.org/proposal-format-2026.pdf",
    "from": "sangam",
    "order": ["A1", "A2", "A3", "A4", "A5", "T1", "A13", "A15"],
    "overlays": {"A1": {"text": "Up to 2,000 characters, including risks", "max_chars": 2000},
                 "A5": {"text": "A table by quarter, Q1 to Q12, with target and means of verification"}},
    "questions": {"T1": {"label": "Convergence with government", "ask": "How does the project work with government programmes?", "ref": "§6"}}
  },
  "skipped_template": false,
  "docs": [{"document_id": 57, "name": "annual-report-2024-25.pdf", "added_at": "2026-10-09T10:05:00Z"}],
  "style": "Plain, specific English for a CSR programme officer …",
  "drafted_at": "2026-10-09T10:06:30Z",
  "sections": {
    "A3": {"text": "In Baksa's Tamulpur block, 62% of households grow one crop a year (SeSTA baseline 2024) … [Add: the main cause, with a source]",
           "sources": ["doc:41", "ref:210"], "missing": ["The cause"], "score": 1,
           "checked_hash": "9f2c…", "done": false, "rev": 4},
    "A15": {"text": "…", "sources": ["doc:58"], "missing": [], "score": 2,
            "checked_hash": "51ab…", "done": true, "rev": 2}
  },
  "suggestions": [{"id": "s1", "section": "A11", "text": "In 2021–24 SeSTA ran …", "source": "doc:57"}],
  "polished": {"at": "2026-10-09T12:05:00Z", "sections_hash": "c41e…",
               "text": {"A2": "SeSTA will work in 60 villages across two aspirational districts of Assam …"}},
  "versions": [{"n": 1, "document_id": 71, "at": "2026-10-09T11:20:00Z", "by": "7b1e…"}]
}
```

**How the fields work**
- `step` is where the proposal reopens.
- `funder` is a **snapshot**, written when the proposal starts: the funder brief (F1's blurb) and the
  gate requirements with what Sangam holds. It does not change under the person's feet; **Refresh** in
  step 1 rereads it.
- `template` is null when skipped (`skipped_template: true`) or not yet chosen. `from` is `sangam`
  (the funder's record, possibly edited: then `user`) or `upload`. `order` is the document's section
  order; without a template it is the rubric's.
- `docs` lists the documents added in this proposal's step 2. The documents themselves are ordinary
  Doc Vault rows; drafting also reads the organisation's other documents.
- `sections` holds every drafted section by rubric code: its text, the sources it was drafted from,
  what is missing, its score, the hash of the text last checked, Done, and `rev` (see *Saving*).
- `polished`: the last polish, with the hash of the sections it was written from; null until the
  first polish.
- `suggestions`, `versions`: as described above. Every version is a saved polish.

**`summary`**, written on every save from `work` in code (`proposals/readiness.py`, the same function
the page uses), so the list never reads `work`:

```json
{"step": 3, "done": 9, "total": 19, "core": 24, "core_max": 32, "funder": 3, "funder_max": 6,
 "overlays_met": 1, "overlays": 2, "gates_met": 2, "ready": false, "missing": ["A6 below 2", "A5 overlay"]}
```

**Size.** About 2 KB a section; a whole `work` is 40–60 KB. The list reads only `summary`, under 0.3 KB
a proposal.

### The document

The sections are the person's content; the document is written from them. Articulation is the point,
not layout.

**Polish.** One `Settings.model` call over the whole proposal: every section's text, the writing
style, the template's order, headings and limits. It returns the proposal rewritten section by
section, as `{code: text}`. The prompt holds it to:
- the writing style, and the template's headings and order (the rubric's without a template);
- joining the sections into one argument: no repeated facts, consistent figures and names;
- the template's character and word limits, checked again in code afterwards;
- **no new facts**: only what the sections say, with sources kept as short parentheticals
  ("SeSTA household survey, March 2026");
- every `[Add: …]` kept, so a gap is never papered over.

The result is stored in `work.polished` with the hash of the sections it was written from. When the
sections' hash no longer matches, the page shows the stale banner.

**The .docx** is built on the server from `work.polished`, never from what the browser holds, and kept
plain: the proposal's name as the title, the funder and date under it, then the sections under their
headings. No cover page, contents page or house styling. Any `[Add: …]` still in the text is
highlighted, so a gap cannot go out unnoticed, and Save says how many remain.

It is written to the vault bucket at `<org_id>/proposals/<proposal_id>/v<N>.docx`, gets a `documents`
row (`doc_type 'proposal_draft'`, `is_public false`, `is_ai_generated true`, `org_id`, `funder_id`,
`uploaded_by` the caller), is appended to `work.versions`, and `draft_document_id` points at it.
Saving again makes version N+1; earlier versions stay.

**Finalising happens outside Sangam.** The person downloads the .docx and finishes it in Word. A
Word-edited copy is not uploaded back: the versions are only those Sangam assembled, and the page says
that changes made in Word are not in Sangam's sections.

**New dependency:** `python-docx`, to write the .docx and to read uploaded .docx.

### Reading uploads

Today `routes/documents.py::_extract` reads text from PDFs only, so a workplan in Word or a budget in
Excel would give drafting nothing. This spec extends it:
- `.docx` with `python-docx` (paragraphs and tables);
- `.xlsx` with `openpyxl` (already a dependency), each sheet as a small Markdown table, capped.

Other types are stored with no text, as today, and the page says Sangam could not read them.

## Saving

Every change is saved as it happens: a gate tick, the template, an upload, the style, a section's
text (after a second's pause in typing), Done, Add or Dismiss.

**Edits are saved field by field, not as the whole `work`.** The page sends only what changed:

```json
PATCH /api/proposals/42/work
{"set": {"sections.A3.text": "…", "sections.A3.done": false}, "rev": {"A3": 4}}
```

- The server applies each path with `jsonb_set` in one statement (creating a missing parent object
  first, since `jsonb_set` does not), inside a transaction that locks
  the row, then recomputes `summary` and `updated_at`.
- Paths are checked against an allowlist of the shapes above; anything else is a 400.
- **A section's text carries its `rev`.** If it does not match the stored one, somebody else changed
  that section since this page loaded it: the server answers 409 with the current section, and the
  page reloads that section and says "Updated by someone else". Otherwise `rev` goes up by one.
- Two people working on different sections, or on a section and a gate, never clash.

The server's own writes (a drafted section, a template read, suggestions, a version) use the same
locked update and bump the section `rev` they touch.

## API

A new `proposals` resource: router, repository, schema, one line in `api/router.py`. Every route runs
as the caller and sits behind `require_user`; a proposal the caller cannot see is a 404.

| Route | Does |
|---|---|
| `GET /api/proposals?org=<slug>&funder=<id>` | The list: id, title, org, funder, `created_at`, `summary`. Both filters optional; with none, every organisation the caller can see. |
| `POST /api/proposals` `{org, funder_id, title}` | Starts one, reads the funder brief, returns it (201). Always a new proposal, even when others to that funder exist. |
| `GET /api/proposals/{id}` | The proposal with its `work`. |
| `PATCH /api/proposals/{id}` `{title}` | Renames it. |
| `PATCH /api/proposals/{id}/work` | Field-by-field save, above. |
| `POST /api/proposals/{id}/template` | `{url}`, `{document_id}` or `{skip: true}`. A URL is fetched through `guarded_client` and stored as a `proposal_template` document; the text is read into `work.template`, and `proposals.template_id` is set to the same document (null on skip). |
| `POST /api/proposals/{id}/sections/{code}/draft` | Drafts one section and saves it. |
| `POST /api/proposals/{id}/sections/{code}/check` | Checks one section and saves the score. |
| `POST /api/proposals/{id}/suggestions` `{document_id}` | Reads a new document against the sections and saves the suggestions. |
| `POST /api/proposals/{id}/polish` | Polishes the whole proposal and saves it in `work.polished`. |
| `POST /api/proposals/{id}/versions` | Builds the .docx from `work.polished` and saves it as a version. |

Uploads use the existing `POST /api/documents/uploads` and `POST /api/documents`.

`backend/app/proposals/` is a new group, per the layout rule: `rubric.py`, `readiness.py`, `sources.py`
(the source pack), `draft.py` (drafting, checks, the funder brief, template reading, suggestions), and
`polish.py` (the polish call) and `assemble.py` (the .docx). Model prompts live next to them as `.md` files.

## Access

One migration, `0036_proposal_work.sql`, besides the columns:

- **Proposals:** replace `proposals_insert` and `proposals_update` so they use `app.my_org_ids()` (members,
  admins and stewards) `OR (SELECT app.is_staff())`, instead of `app.my_writable_org_ids()`. Reading is
  unchanged.
- **Documents:** replace `documents_insert` the same way, so a steward can upload in step 2 and the
  assembled versions can be saved as the caller.
- **The upload routes** call `org_id_for_member(..., write=True)`, which excludes stewards. They change
  to `write=False`; the policy is what decides.

**This changes what a steward is.** 0004 defined a steward as someone who reads and never writes. After
this, a steward can write proposals and upload to an organisation's Doc Vault, nothing else. That is
the decision recorded in the Funder Match spec ("stewards can start proposals too").

**Not in Ask Sangam's catalog.** `proposals` stays in `KNOWN_EXCLUDED`. Proposal text is private and
Ask's SQL tools run as the owner until #114.

**Provenance.** Proposal text is written, not scraped: it carries `rubric_version`, every section
lists its `sources`, and the assembled documents are marked `is_ai_generated`.

## Testing

- **Unit:**
  - the rubric's readiness rule, including no core 0, the three must-be-2 sections and overlays;
  - display codes for A, B, C and F, with and without F4 and T sections;
  - `summary` from a fixed `work`;
  - the PATCH path allowlist, the section `rev` 409, and fields on different sections not clashing;
  - .docx assembly from a fixed `work.polished`: order, headings, highlighted gaps;
  - the stale-polish check when a section changes;
  - .docx and .xlsx text extraction;
  - routes through `client_for` with the repository and the model calls patched.
- **Integration** (`integration` mark):
  - the row-level rules: member, admin, steward, staff, stranger and anonymous creating, editing and
    reading a proposal, and uploading a document;
  - two proposals from one organisation to one funder, each saved and assembled independently.
- **Evals** (`eval` mark, costs money): draft three sections for a seeded organisation and assert the
  text cites only markers from its source pack and leaves `[Add: …]` where the pack has nothing.
- **Frontend:** `npm run lint`, `npm run build`, and the flow by hand as a member and a steward: start
  from Funder Match, the three steps, a document added after drafting, assemble, reopen at each step,
  phone width.

## Order of work

1. Migration 0036, the rubric, `readiness.py`, and the `proposals` resource with create, read, list
   and PATCH.
2. Upload extraction for .docx and .xlsx.
3. The funder brief, template reading, the source pack and drafting.
4. Checks and suggestions.
5. Polish, the .docx and versions.
6. The page, the sidebar item, the Funder Match buttons, and the design-system sync.

## Decisions taken

Confirmed on 9 Oct 2026 against prototype version 20:
- **Several proposals per organisation and funder**, one per programme, named at start and renameable.
  A card with several shows **Proposals (N)**, opening the list filtered to that funder.
- **Stewards upload anywhere in the organisation's Doc Vault**, not only from a proposal.
- **Staff can start and edit** any organisation's proposals.
- **F2 Earlier phase** appears only with a past partner line with this funder, or when the template
  asks about an earlier phase.
- **No upload back** of a Word-edited .docx.
- **Drafting and polishing on `Settings.model`**; checks, template reading and suggestions on `utility_model`.
- **Assemble, then polish:** Assemble shows everything as entered; one Polish pass writes the proposal
  in the style and template order without adding facts; only polished text is saved as a .docx.
- **Polished text is read-only**: changes go into the sections, then polish again.
- **Polish is allowed with gaps open**; they stay marked.
- **A plain .docx**: no cover page, contents or house styling.

## Open after this spec

- **v2:** remembering gate answers per organisation; editing the same section together.
- **#126** must merge first: the Funder Match page, and `funder_matches` for the fit shown on the list.
- **#114:** after it is fixed, whether Ask Sangam may read proposals.
- **Cost:** drafting is about 20 model calls a proposal, and each polish one large call. Measure it on the first real proposals before
  deciding whether drafting should be cheaper.
