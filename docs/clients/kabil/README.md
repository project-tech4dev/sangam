# KABIL — funder intelligence

What Sangam is doing for KABIL: which funders have been researched on their behalf, what the
evidence says, and what is still missing. Written 2026-09-29.

KABIL (Kishangarh, Delhi; field offices in Udalguri and Mazbat, Assam) is a registered society
working on rural livelihoods with tribal and marginal-farmer households in Bodoland. It is the
cohort organisation with the deepest hand-vetted record, which is why it is the worked example
for everything below.

> **How to read this file.** Every claim here traces to either the hand-vetting sheets in
> `org-grant-intelligence/hand-vetting/`, the seeded rubric data in `seed/data/rubrics/`, or a
> run of Sangam Import. Where a figure is missing it says *not recorded* — which means nobody has
> put it in the catalog, never that the thing does not exist.

## The funders assessed for KABIL

Four, hand-vetted on 10 September 2026 against rubric v1 by a single rater doing desk
verification, then re-scored under v2.

| Funder | v1 | v2 | Relationship |
|---|---|---|---|
| Axis Bank Foundation | **93**/100 | 93/100 | Funded KABIL in Udalguri with ASRLM — a four-year livelihoods project from April 2018 targeting 15,000 SHG families. Grant **concluded (2018–22)**. |
| Azim Premji Foundation | **90**/100 | 88/100 | Mazbat work; all v1 criterion scores confirmed in vetting |
| SBI Foundation | **87**/100 | 81/100 | Grant **active** — the freshest relationship of the four |
| Tata Trusts | **64**/100 | 56/100 | Three of seven v1 scores moved during vetting, the largest correction in the set |

Two things the scores do not say on their own:

- **v2 has not been hand-vetted.** The v1 numbers carry a human check dated 10 Sep 2026; the v2
  numbers are a sub-criteria pass and were explicitly *not* vetted as of 21 Sep 2026. Quote v1
  when the number matters.
- **A high score is not a live relationship.** Axis Bank Foundation scores highest and its grant
  concluded in 2022. SBI Foundation scores lower and is current. Fit and recency are different
  questions and the rubric only answers the first.

## What the catalog holds, and what it does not

KABIL's own record is the strongest in the cohort: registration (Society, 21 Dec 2012), PAN, 12A,
80G and FCRA numbers, three offices, programme history with named funders, and beneficiary
figures — each with the source URL and the quoted sentence behind it.

Three gaps matter for fundraising, and all three are measured rather than assumed:

- **No Darpan Unique ID.** The portal CAPTCHA blocks automated lookup and no cached third-party
  copy quotes it. A person has to fetch it by hand.
- **CSR-1 is recorded as not available**, verified against give.do. Under the v3 eligibility gate
  this **blocks** any match with a Section 135 funder until it is fixed — the single highest-value
  action on this list.
- **No audited financial statement is published anywhere public.** Three years of income is a
  standard eligibility gate.

## What a funder application would currently fail on

`check_template()` was run for KABIL against the SBI Foundation Gram Seva RFP (November 2024,
now closed) — 59 template items:

| | Count | Examples |
|---|---|---|
| Pass | 9 | 13 years since registration; works in Udalguri, which is on the RFP's district list; 12A, 80G, FCRA, PAN on file |
| Fail | 1 | Form CSR-1 — not available (give.do, verified) |
| Missing | 27 | three years of income against the ₹5 crore gate, board members, one measured outcome, 24 checklist documents |
| Manual | 22 | log frame quality, exit strategy, political or religious affiliation |

That "missing 27" is the work list. It is not a judgement about KABIL; it is what a funder asks
for and the catalog cannot yet answer.

## The evidence problem in KABIL's impact data

Four results chains are recorded. Every one of them stops at **output**:

| Chain | Has | Missing |
|---|---|---|
| Axis Bank Foundation, Udalguri | 24,765 families against a target of 15,000 | adoption, outcome, sustained outcome, impact, SROI |
| Azim Premji Foundation, Mazbat | 2,000 farmers trained, 2,417 households; adoption of rain shelters and trellises | outcome onward |
| Mazbat 2024 onward | 15 SHGs with plans; income-up target for 2,000 households | everything past output |
| DWIMU | 4,000 of 10,000 households with plans submitted | everything past output |

**No chain has a baseline or a comparison group.** That is the gap the whole product exists to
surface: the data stops at "we trained" and "we reached", which is exactly what a funder asking
for evidence of change will push back on.

## Funder-side research, and what it found

Sangam Import was pointed at Axis Bank's public disclosures on 29 Sep 2026. It reached the Tier-1
sources unaided — the BRSR, the Integrated Annual Report, the Axis Bank Foundation annual report
and the ESG data book — and navigated the 400-page integrated report to the CSR annexure.

Recorded for Axis Bank, each with its source article and the printed wording kept alongside:

| FY | Prescribed CSR | Spent |
|---|---|---|
| FY2022-23 | ₹199.46 cr | ₹172.31 cr |
| FY2024-25 | ₹425.92 cr | ₹427 cr |
| FY2025-26 | ₹529.49 cr | ₹421.66 cr |

Read against KABIL: Axis's CSR budget has roughly **tripled since FY2022-23**, while its grant to
KABIL concluded in 2022. A funder spending more each year and no longer funding you is a
re-approach case, not a closed one.

**What the importer could not yet save.** It can write funders, their identifiers, annual CSR
position and source documents. It cannot yet write project-level spend, district footprints,
implementing partners, grants, programmes, metrics or contacts — those have no writer. So the
partner list it read out of the Axis Bank Foundation annual report (CINI, Harsha Trust, Rajarhat
Prasari, PRADAN, and a roster of 46 under the Sustainable Livelihood Programme) exists only in
that conversation. Until `funder_partners` has a writer, partner overlap between KABIL and a
funder cannot be computed.

## What would change the picture most

In order of effect on KABIL's ability to raise money:

1. **Fix CSR-1.** It is one registration and it currently blocks every Section 135 funder.
2. **Publish three years of audited accounts**, or get them into the vault. It is the most common
   hard eligibility gate.
3. **Get one outcome measured with a baseline**, on any chain. One credible outcome changes what
   can be claimed across all four.
4. **Re-approach Axis Bank Foundation.** The relationship is warm, the work is documented, and
   their budget has tripled since it ended.
5. **Get the Darpan ID by hand** — a five-minute CAPTCHA that nothing automated can do.

## Where the facts come from

| | |
|---|---|
| Organisation profile, registrations, programmes, contacts | `org-grant-intelligence/hand-vetting/KABIL_Fact_Check_Verified.md` — nine sections, every claim with its quoted sentence and source URL |
| Funder profiles | `hand-vetting/KABIL_Funder_{AxisBankFoundation,AzimPremjiFoundation,SBIFoundation,TataTrusts}.md` |
| Rubric scores | `seed/data/rubrics/{v1,v2,scores}.json`, loaded by `make seed` |
| Template check and impact chains | the v3 data-model work, `docs/DATA_PLATFORM.md` |
| Axis CSR figures | Sangam Import run, 29 Sep 2026, source India CSR with the article URL on every row |
