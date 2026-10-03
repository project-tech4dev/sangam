---
name: ngo-brief-for-funders
description: Use when someone names one or more NGOs, CSOs, trusts or societies — organisations that RECEIVE funding rather than give it — and wants the brief a funder's CSR team would read before a first conversation. Covers statutory standing (12A, 80G, FCRA), income and programme spend, where it works, what it has reached, and who funds it already. Produces one profile per organisation and, for several, a comparison. Not for a company, corporate foundation or CSR arm — use funder-scan-for-fundraisers for those. Not for a single fact about an organisation already in the catalog, which funder_dossier answers in one call with entity_kind set to org.
---

# A brief a funder would read before the first meeting

The reader is a CSR or grants lead deciding whether an organisation is worth
a conversation. They are asking three things in order, and the order matters:
**can we legally give them money, what would it do, and has it worked before?**
A profile that describes the mission beautifully and cannot answer the first
question has failed, because the first question ends the conversation.

Research each organisation against this list, in this order, and put the
result in one section per organisation.

## The fields

**Can we give them money** — 12A · 80G · FCRA, each with its number as
printed, its date, and whether it is current. These three are the gate, and
each is a separate fact: 80G is what makes a donation deductible, FCRA is what
makes foreign money lawful, and 12A is neither. A lapsed or surrendered
registration is a finding, not an absence — say which it is. Then PAN, Darpan,
CIN or registration number, and the legal form as printed ("Public Charitable
Trust", "Society", "Section 8 Company" — these are not interchangeable).

**What size of organisation** — total income, programme spend, non-programme
spend and foreign contribution for the latest financial year and the two
before it, each against its year, each marked audited or not. Programme spend
is not total spend; total income is not grant income; foreign contribution is
the FCRA return's figure, never inferred from a donor list. A ratio is worth
reporting only when both halves came from the same statement.

**What the money does** — programmes with their themes, phases and dates.
Keep the organisation's own wording for a theme beside any normalised one.

**Where** — states and districts where work actually runs, with the role
(registered, operates, funds). A district always travels with its state. The
registered address is one of these with role `registered`, not a separate fact.

**What it has reached** — beneficiaries, outputs and outcomes, each with its
value, unit, period and stage, and the method behind it. **Never describe a
self-reported figure as independently verified**, and never report a cumulative
"since inception" number as an annual one.

**Who funds it already** — named funders and grants where disclosed. An
existing CSR funder is the single most useful line in this brief: it says
somebody did this diligence and said yes. **It is the one field here with no
finding behind it.** `grant` is a funder-side concept — a `GrantFinding`
records money a funder GAVE, and there is no org-side counterpart for money
received, because `grants.org_id` is NOT NULL and `orgs` has no writer. So
this line comes from two places: the researcher's prose summary, which is
asked to name any funder it saw, and `funder_dossier` with `entity_kind='org'`,
whose "grants received" section covers only an organisation already in the
catalog. Say which of the two it came from, and say "not recorded" rather
than leaving it out.

**Evidence** — the latest annual report, audited accounts, FCRA return and
Darpan listing, with a source link for every important figure.

## Sources, in order

Official first: NGO-Darpan, the FCRA portal, the organisation's audited
accounts and annual report, 12A/80G orders where published, MCA for a Section
8 company. Then the organisation's own site. Then GuideStar India, Credibility
Alliance and similar directories, which are useful and are secondary. Credible
news last, and marked as such.

## Three things not to conflate

**Not publicly disclosed** — the organisation did not publish it.
**Found, not yet storable** — it published it and no column exists for it.
**Not recorded** — nobody has looked yet.

The researcher reports the goals it worked to, which are the fields with a
column. Say which of the three you mean: writing "Not publicly disclosed" over
a field we simply cannot store misrepresents the organisation, and in this
brief it misrepresents it to a funder.

## Do not score

No rating, no tier, no "strong candidate". A funder's own criteria decide
that, and a score invented here is a judgement wearing a citation. Report what
is true and let the reader weigh it.

## The comparison

For several organisations, one table after the sections: statutory standing
(12A / 80G / FCRA, each present, lapsed or not found) · latest total income ·
latest programme spend · states · primary themes · existing CSR funders ·
latest year with audited accounts.

Build every line from what the researchers stored, except "existing CSR
funders", which has no finding behind it and comes from the summary or the
dossier as described above. An empty cell is ambiguous, so never leave one —
write "not recorded" or "not disclosed", whichever is true.

## What stays research

None of this becomes a catalog row yet: `orgs`, `org_identifiers`,
`org_financials` and `org_locations` have no writer. The findings are saved,
the brief is published and the entity file renders — say that plainly rather
than offering a promotion that will be refused.
