# Sangam Pitch: public research reader — Draft v4 (small)

> Once approved, this file is committed as `docs/features/2026-10-20-pitch-public-research.md` on a new branch
> `feat/pitch-public-research` (a worktree off `master`; other sessions share the checkout) before any code.
> It replaces the `landscape-reader` entry under "Later" in `docs/features/2026-10-14-proposal-copilot.md:761`.

## Context

Sangam Pitch writes only from cited facts, and today those come from the org's own files, the registry, the Funder
Match and Import's funder brief. Nothing brings in public evidence, so Context, Problem and baseline, and Fit with
funder priorities stay `[Add: …]` gaps. Examples of the missing evidence:
- the district's own figure;
- the scheme already working on the problem;
- the SDG target the work serves;
- what worked elsewhere.

## Goal

**When Priya presses "Write the first draft" in step 2, one more reader, "Public research", runs beside the file
readers and adds cited public facts to the fact list. She confirms or drops them there, like every other fact.**

## What changes

```
 "Write the first draft" → read_files
      ├─ one reader per ticked file      (as today)
      ├─ funder reader                   (as today)
      └─ public research reader  (new)   task: district, state, theme   ← public data only
             tools: search_public_sources · read_page · fetch_document · read_document_pages · add_facts
             add_facts: the quote must be on a page it read  → fact list (amber, "From public research")
```

1. **The reader: `backend/app/proposals/readers.py`.**
   - A third key, `public`, next to `FUNDER`. `pending()` lists it, so "Try again" retries it like any file.
   - It runs with `run_sources.Sources(web=True)`.
   - It is built only when `TAVILY_API_KEY` is set. Without the key, `pending()` skips it and nothing fails.
2. **Its task holds public data only: `readers._task`.**
   - It gets the org's district and state from the registry, the theme from the saved Funder Match, and the
     proposal's sections.
   - It gets the org's name only as "never search for this". It never sees the org's files, the fact list or the
     chat.
   - *Example:* SeSTA's private "38% out of school" can't reach a search, because the reader never sees it.
3. **The prompt: `backend/app/proposals/prompts/public_researcher.md` (new).**
   - Your pasted prompt, covering the five kinds of evidence:
     - the problem in the district, state and India (Census, NFHS, NSS, UDISE+, NITI Aayog, state reports, academic
       studies, UNICEF/WHO);
     - why this place;
     - government priorities (state schemes, national missions, district plans);
     - SDGs;
     - what worked elsewhere.
   - Facts go to fixed sections: problem and place → A2 and A3; government → F1 and A14; SDG → F1; similar work → A4.
   - It quotes exactly and never drafts proposal text.
   - The CSO's own figures still come from the file readers, as today.
4. **Two small guards.**
   - **No org name:** a middleware in `proposals/middleware.py` refuses a `search_public_sources` call that names
     the org.
   - **Quote on the page:** a middleware keeps the text of every page this reader read. `add_facts` then refuses
     this reader's web fact unless its quote is on that page (`facts.norm`) and it has a year.
5. **Small edits elsewhere.**
   - `work.py:30` `_READER` gains `public`.
   - `agent.py` adds a `PUBLIC_TOOLS` list.
   - `facts.make` keeps a `found_by: "public"` key.
   - `instructions.md` rule 7 mentions the public research.
   - A one-line hint for writing Problem and baseline: put the org's own figure beside the district, state or India
     figure for the same indicator.
6. **Screen.**
   - The reading list in step 2 (`ProposalShell.tsx` `Reading`) shows a "Public research" row with no other
     change.
   - `FactList.tsx` labels these facts "From public research", and `factsFrom` (`:573`) tells them apart from the
     funder reader's.
   - The CSS reuses existing classes.

Nothing new: no endpoint, no table, no migration, no panel, no approval step.

## Tests (unit, no database)

- The public reader carries exactly its five tools; the file and funder readers still carry no web tool
  (`test_proposal_readers.py:47` narrowed to those two).
- `pending()` lists `public` only when the Tavily key is set; "Try again" retries it alone.
- The org-name guard refuses "SeSTA dropout" and allows "dropout Udalguri UDISE+".
- `add_facts` inside this reader:
  - refuses a quote that is not on a page it read;
  - refuses a fact with no year;
  - keeps a good one with `found_by`.
- Outside this reader, web facts keep today's rule.
- The task text never contains a Doc Vault fact's value.

## One PR

- **Tasks:**
  - [ ] commit this plan
  - [ ] the reader, prompt and guards
  - [ ] the `add_facts` check
  - [ ] the small edits
  - [ ] the screen label and row
  - [ ] the tests
  - [ ] edit decisions 11 and 21 and criterion 12 in the copilot plan
  - [ ] a `CHANGELOG.md` line and `make wiki-update`
- **Verify:**
  - `cd backend && pytest tests/test_proposal_*.py && ruff check .`
  - `cd frontend && npm run lint && npm run build`
  - Locally, SeSTA → ABF: "Write the first draft" gives a "Public research" row and amber facts, each quote found
    on its page. The Langfuse trace shows no search naming SeSTA.
  - Browser check as a steward and at phone width.

## Risks

- **A quote check that is too strict** can refuse figures from tables (NFHS, UDISE+). The local run shows how often.
- **No district on record:** the reader searches at state level, and the gap is visible in the fact list.
- **Cost:** one Tavily and Sonnet run per "Write the first draft"; "Try again" reruns only what failed.
