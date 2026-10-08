---
name: funder-intake-research
description: Use when someone names one or more companies, corporate foundations, trusts or grantmakers and wants to know what it would actually take to reach their money. Pulls ten fields per funder, in intake order — route and whether it is live, the receiving legal entity, grantmaker or implementer, eligibility split into statutory restatement and the funder's own bar, the document checklist verbatim, hard disqualifiers, district-level geography, grant size and co-funding, live call or historical disclosure, and provenance with access state — plus the open call itself when field 9 found one. Raw field-value-source only; no verdicts, no tables, no scoring. Not for an organisation that receives money — use ngo-credential-research. Not for a single fact about a funder already in the catalog, which funder_dossier answers in one call.
---

# What we want pulled for a funder

Ten fields, every one of them, in the order below, and an eleventh that
fires only when field 9 says there is a live call. The order is how much not
knowing the field stalls an NGO — not how prominently the funder writes about
it. Fields 1 and 2 are "is there a door here at all"; get those wrong and
every other field describes the wrong body.

## The rules that hold for all ten

**Every value carries its exact source URL. Including "not stated".** A field
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
the source of a fact. Only the funder's own domain, or a primary document it
hosts.

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

## When a source will not open

Try the Internet Archive snapshot of the same URL before giving up, and label
the result `archived`. If a primary legal source (mca.gov.in, csr.gov.in,
indiacode.nic.in) is unreachable, say so and say that any statutory claim is
corroborated from professional commentary instead of read directly — that is
weaker evidence and is labelled as such, not presented as equivalent.

## What this skill does not do

It does not decide fit, score a funder, rank a list or lay out a comparison.
It does not write to the catalog. It produces ten cited fields per funder,
plus any open call it found, and stops.
