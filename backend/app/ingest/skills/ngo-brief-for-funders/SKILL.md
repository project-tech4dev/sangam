---
name: ngo-brief-for-funders
description: Use when several NGOs, CSOs, trusts or societies have been researched and a funder's CSR or grants team needs them side by side to decide which are worth a conversation — who clears the statutory gates, at what scale, working where. Produces the comparison across organisations, not the research behind it. What to pull for each organisation is ngo-credential-research; the record for one organisation on its own is entity-record. Not for a company, corporate foundation or CSR arm.
---

# The comparison a CSR team acts on

The reader is deciding who gets a first meeting. They ask three things in
order, and the order matters: **can we legally give them money, what would it
do, and has it worked before?** A comparison that describes missions
beautifully and cannot answer the first question has failed, because the
first question ends the conversation.

The fields come from `ngo-credential-research` and the per-organisation
record from `entity-record`. This skill is only the table across them.

## The table

One row per organisation, in this order: **statutory standing** — 12A, 80G,
CSR-1, each present or not, with the blocking one named · **FCRA, separately**
· **DARPAN and blacklist status** · **three years of audited accounts, yes or
which years are missing** · **latest programme spend with its year** ·
**states and districts** · **primary themes** · **existing funders** ·
**permanent staff count**.

Statutory standing leads because it is the only column that can end the
conversation on its own. An organisation doing excellent work without CSR-1
cannot receive Section 135 money this year, and a table that sorts by
programme spend buries that.

## Rules that keep it honest

**Evidenced and claimed are different columns' worth of difference.** A
homepage sentence saying "we are 12A registered" does not clear a gate. Mark
every credential as evidenced or claimed and never let a claim satisfy a cell.

**Name the blocking gate, never just "ineligible".** "CSR-1 missing" and
"80G and CSR-1 missing" and "12A cancelled, under appeal" are three different
next actions.

**A cancellation under appeal is still a cancellation.** Appeal status is its
own note beside it, never a resolution.

**Never treat a self-reported figure as independently verified**, and never
report a cumulative reach number as an annual one.

**Existing funders has no finding behind it.** `grant` is a funder-side
concept and `grants.org_id` is NOT NULL, so this cell comes from the
researcher's prose summary or from `funder_dossier` with `entity_kind='org'`.
Say which, and write "not recorded" rather than leaving it out.

**Refuse to score.** A funder's own criteria decide fit, and a rating invented
here is a judgement wearing a citation.

## Three things never conflated in a cell

- **not disclosed** — the organisation did not publish it
- **found, not storable** — they published it and no column exists for it
- **not recorded** — nobody has looked yet

## What is stored and what is not

An organisation's research promotes, so the comparison may well be describing
rows the catalog holds. Two things it still does not hold, and a cell that
depends on either says so: an NGO's **website**, which has no column, and any
figure on an organisation the catalog already states differently — that
difference is reported for a person, not stored.
