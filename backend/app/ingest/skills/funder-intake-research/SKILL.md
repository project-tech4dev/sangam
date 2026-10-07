---
name: funder-intake-research
description: Use when someone names one or more companies, corporate foundations, trusts or grantmakers and wants to know where their CSR money goes and what it would take to reach it. Sets the source order — by strength of evidence — statutory CSR filings under the corporate filer, then the funder's own publications, then recipient-side records — with the staff workbooks (read_source_rows) read once, after all web reads — and pulls ten fields per funder in intake order — route and whether it is live, the receiving legal entity, grantmaker or implementer, eligibility split into statutory restatement and the funder's own bar, the document checklist, hard disqualifiers, district geography, grant size, live call or historical disclosure, provenance with access state; plus the open call and the rule for classifying spend lines. Raw field-value-source only; no verdicts, no scoring. Not for an organisation that receives money — use ngo-credential-research. Not for one fact already in the catalog — funder_dossier answers that.
---

# What we want pulled for a funder

Ten fields, every one of them, in the order below, and an eleventh that
fires only when field 9 says there is a live call. The order is how much not
knowing the field stalls an NGO — not how prominently the funder writes about
it. Fields 1 and 2 are "is there a door here at all"; get those wrong and
every other field describes the wrong body.

## Where to look, in this order

The order is strength of evidence for money, not the order of reading. The researcher's STEP 1
confirmation search always comes first. **`read_source_rows` is called once, AFTER every web
read** — its first call closes the web tools for the rest of the run — so the staff workbooks
below (#1 filings, #3 CSO workbook) are read last, together, whatever their rank here.

1. **Statutory CSR filings for the corporate entity.** The filer carries the Section 135
   obligation — often the parent company, not the foundation that runs the programmes.
   - Read them with `read_source_rows` (last, see above), under the filer's registered name, then the foundation's.
   - Record the filer as the parent and the foundation as its child (`funders.parent_id`). Never merge them.
   - Per fiscal year, the company-level figures (average net profit, prescribed CSR, spent,
     local-area spent) go to `funder_csr_years`, once per company-year.
   - Each project line goes to `funder_activity` with `kind = 'spend'`: project, filed sector,
     state, district, outlay, amount spent, implementation mode, and the partner when named.
2. **The funder's own publications** — foundation and parent annual reports and the CSR annexure,
   CSR policy and annual action plan, impact-assessment report, BRSR. The funder's own programme
   split ("₹X on programme A this year") is a `kind = 'programme'` row per component per year —
   never spread across filing lines, never added to them.
3. **Recipient-side records** — the staff CSO workbook and recipients' own annual reports — for
   grant amounts per partner, which funders rarely publish. Each is a `partner` finding for the
   funder: the recipient as `partner_name`, the amount as printed with its unit.
   - **An exact fiscal year** (`FY2023-24`) gives that fiscal year and the amount.
   - **A range** (`2021–2024`, `2023-26`, `2022-2025 (Closed)`) gives the **last** fiscal year of
     the range — the one ending in its closing year — and **no amount**; the range is quoted in
     the evidence. A multi-year figure on one year's line would misstate it.
   - **No closing year** (`Post 2022`, `Ongoing`): no finding; name it in the summary.
   - Partner findings are saved in a **funder** research run; an NGO run does not write them.

### Reading the staff workbooks

Call `read_source_rows` once, after all web reads: the first call closes the web tools for the run.
It returns rows as `cell=value` with a `[source:<document>#<sheet>!<cell>]`
marker. Cite the cell that holds the fact. The dataset's `source_url` (a `.invalid` address) is
cited, never fetched. The tool does not convert units; these notes say how each kind of sheet reads.
The researcher reads the sheets itself, web first and staff last, from the same notes in its own
prompt ("The staff sheets"); a supervisor does not read them for it.

- **Filing exports (`mca_csr`).** One row per project line per fiscal year; amounts in **crore**.
  The filer's company-level figures repeat on every project line of a year — take them once. Where
  two columns share the header `State`, the left one is the filer's registered state, the right
  one the project's. One export has a sheet per fiscal year (pass the year as `sheet`); the other
  has one sheet with a fiscal-year column and a group-company column beside the filer.
- **The CSO workbook (`ffrh_funder_datasets`)** has three sheets:
  - a **profile sheet**, one row per CSO, headers on row 2 — the CSO's own account, so `claimed`;
  - a **funder-details sheet in side-by-side blocks**, one block per CSO: the CSO's name in row 1
    above its block, the block's headers in row 2. A funder row belongs to the CSO named in row 1
    at or left of its columns. Amounts are headed ₹ but a cell may carry its own unit
    (`<n> Lakhs`, `<n>Cr`, `<n>,<nn>,<nnn>`): the cell's unit wins. A cell that is not a number
    ("Not disclosed", "<n> and materials") has no amount;
  - a **funders-and-partners sheet in numbered sections**, one per CSO, each with a funders table
    and a partners table; amounts in **lakh**. The note in cell A2 states the unit and caveats —
    read it. The type column uses codes D (domestic), F (foreign), G (government), CSR (corporate
    CSR). The tool shows the section heading and the table's header row with each match.
- Contact columns are removed by the tool, by design.

## The rules that hold for all ten

**Every value carries its exact source. Including "not stated".** A URL, or a staff workbook's cell marker. A field
with no findable URL is not reported as a fact. "Not stated" with a URL means
we read the page and it was silent; "not stated" with no URL means we did not
look, and those are different answers.

**Mark every value `evidenced` or `claimed`, and never silently upgrade one to
the other.** Evidenced is a document, a number, a certificate, a dated page
that says it. Claimed is a bare sentence with nothing behind it. "We fund
across India" on an about-us page is claimed. A district list in a published
call is evidenced.

**Never cite an aggregator.** NGOBox, Devex, CSR trackers, LinkedIn, news
coverage of a grant — these may point you to the funder's page, they are never
the source of a fact. Only the funder's own domain, a primary document it
hosts, or a staff workbook — the statutory filing or the recipient's own record, held privately.

**Pull raw.** Field, value, source URL, evidenced-or-claimed. One block per
funder, fields in the order below. No summary, no verdict, no comparison
table, no "strong fit" — all of that is downstream and belongs to whoever
reads this.

## The ten, and the eleventh

1. **Intake route, and whether it is still live.** Portal URL, email address,
   or RFP process. Actually check it: does the portal load, is the form from
   2012, does the page still exist. Record the check date. "No stated route"
   is a real and common finding — write it rather than inferring a route from
   a generic contact-us page.
2. **The exact legal entity that receives the application.** Many corporates
   route CSR through a separate foundation, and the policy names the
   foundation rather than the parent. Name the receiving body exactly.
3. **The funder's role** — grantmaker (gives money to NGOs), implementer (runs
   the work itself and solicits corporate payers, not NGO applicants), or
   neither (closed, or informational only). A "Partner with us" page can mean
   any of the three, so say which and quote what decided it.
4. **Stated eligibility, as two separate values.** First, *statutory
   restatement* — Rule 4 of the Companies (CSR Policy) Rules copied into the
   policy (12A/80G/CSR-1, three years track record). Flag it as restatement,
   not as the funder's own bar. Second, *the funder's own additional bar* —
   anything beyond the statutory minimum, in the funder's own words.
   Both are quoted verbatim into one `eligibility_guideline` finding per page,
   in its `statutory_restatement` and `own_bar` fields; it becomes the funder's
   `funder_eligibility` document. Keeping them apart is the point: a funder
   that only restates the law has set no bar of its own, and one merged list
   says it did.
5. **The document checklist, verbatim, item by item.** When one is published
   this is the single richest artefact on the page. "Lists 32 items" is the
   right precision; "requires various documents" is not. List them.
6. **Hard disqualifiers** — thresholds the funder says will get an application
   rejected outright: minimum revenue, minimum years running, minimum or
   maximum board size, political or religious bars, donor concentration
   limits, employee count floors. These are rejections, not credentials; keep
   them out of field 4. They go in the same finding's
   `disqualifiers` field — the same document, because all three are conditions
   on the applicant; a separate heading, because a rejection ground is not a
   credential.
7. **Geography at district granularity.** Districts, blocks or named work
   centres exactly as listed — state level is not an answer. If the finer list
   sits behind a login, say that explicitly rather than reporting the state.
8. **Grant size, duration and co-funding share.** Hard numbers only: a rupee
   ceiling, a duration in years, a percentage cap ("covers up to 90% of
   project cost"). Nothing numeric published means say so; never estimate from
   sector norms.
9. **Live call, or historical disclosure.** Many "CSR information" pages are
   statutory annexures describing money already spent last fiscal year, not an
   open call. Say which. A page naming an implementing agency as "TBD" is a
   live, currently-open slot — flag it.
10. **Provenance: exact URL, fetch date, and access state.** Access state is
    its own value and it is load-bearing, because three of these look
    identical to a careless reader and only one of them licenses reporting an
    absence:
    - **readable** — 200, real text
    - **scanned** — a PDF with no text layer. The page exists and the content
      is unread. Never report an absence from one.
    - **soft-404** — HTTP 200 but boilerplate, or byte-identical to an
      invented URL. Treat as not found.
    - **archived** — read from web.archive.org because the live domain blocks
      or 403s. Flag it; it may be stale.

11. **The open call itself — only when field 9 found one.** Its title as the
    funder names it, the deadline, the grant band, and each stated requirement
    on its own line. It is last because the ten above decide whether to bother
    with this funder at all, and a specific call matters only once they have.
    Three rules, because this is the field most easily invented:
    - **A programme page is not a call.** "Partner with us", a themes page, a
      past-projects list — none of these is an open call, and which one it is
      is field 3's question. No title and no deadline means no call; say so
      rather than manufacturing one.
    - **A closed or expired call is still worth recording**, marked closed. A
      funder that ran a call last year is a funder with a door, and next
      year's re-issue is a new opportunity rather than an edit of this one.
    - **The call's requirements are the call's, not the funder's standing
      bar.** These land in `rfps.eligibility`; field 4's land in
      the `funder_eligibility` document. The same sentence can be true in both places, and
      recording it twice is correct — one is what this call asks, the other is
      what the funder asks of everyone.

## Classifying a spend line: domain and theme

Every domain and theme on a line is an **inference**. Record it as one.

- **Classify by the project name and the named partner**, not the Schedule VII sector filed.
  Filings misfile often.
- **A domain, always** — one of five: livelihoods, health, education, **environment**
  (sustainability, conservation, animal welfare that is not a livelihood programme), **others**
  (relief, sports, administration, unlabelled lines, lines listing several sectors).
- **A theme only as far as the evidence goes**: a sub-theme when the project or partner points to
  one, a theme when only the broad area is clear, none otherwise. Environment and others have none.
- **Record what it rests on**: `classified_by` (`filed_sector` only where unambiguous,
  `project_name`, `partner`, or `report`) and a one-line `classification_note` quoting the
  evidence.
- **The filed sector is saved as filed** in `sector`, whatever the classification says.
- A `programme` row is classified the same way, `classified_by = 'report'`.

## When a source will not open

Try the Internet Archive snapshot of the same URL before giving up, and label
the result `archived`. If a primary legal source (mca.gov.in, csr.gov.in,
indiacode.nic.in) is unreachable, say so and say that any statutory claim is
corroborated from professional commentary instead of read directly — that is
weaker evidence and is labelled as such, not presented as equivalent.

## What this skill does not do

It does not decide fit, score a funder, rank a list or lay out a comparison.
It does not write to the catalog. It produces ten cited fields per funder, the classified
lines, and any open call it found, and stops.
