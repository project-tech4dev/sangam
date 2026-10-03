---
name: ngo-credential-research
description: Use when someone names one or more NGOs, CSOs, trusts or societies — organisations that RECEIVE money — and wants their actual legal and operational standing rather than their sector and mission. Pulls exactly ten fields per organisation in dependency order — 12A and 80G, CSR-1 and its registration number, three years of audited accounts, three years of evidenced similar work, the registration deed, PAN and DARPAN with blacklist status, governing board, permanent staff, financial profile, institutional policies. Raw field-value-source only; no verdicts, no tables, no scoring. Not for a company, corporate foundation or CSR arm — use funder-intake-research. Not for a single fact about an organisation already in the catalog, which funder_dossier answers with entity_kind set to org.
---

# What we want pulled for an NGO

Ten fields, every one of them, in the order below. The order is a dependency
chain, not a priority list: fields 1 to 4 are the statutory gates, each one
blocking regardless of the rest, and 5 to 10 are what funders' own published
checklists ask for beyond a registration number.

## The rules that hold for all ten

**Every value carries its exact source URL. Including "not stated".** A field
with no findable URL is not reported as a fact.

**Mark every value `evidenced` or `claimed`, and never silently upgrade one to
the other.** Evidenced means the organisation's own site, a certificate scan,
a filing or an audited statement shows it — a number, a document, an ID.
"We are 12A and 80G registered" on a webpage, with no number and no
certificate, is **claimed**. It is explicit, it is quotable, and it is still
not evidence.

**A blank government search form is not a source.** An empty NGO Darpan
search box renders identically for every organisation and proves nothing
about this one. Never cite it for any field.

**Adverse findings hide in audited statements, not on homepages.** A suspended
FCRA, a cancelled 12AB, a show-cause notice — check the notes and credentials
sections of the audited accounts specifically. A cancellation under appeal is
still a cancellation; record the appeal status as its own value, never as a
resolution.

**Never cite an aggregator.** Only the organisation's own domain, or a
primary document it has published.

**Pull raw.** Field, value, source URL, evidenced-or-claimed. One block per
organisation, fields in the order below. No eligibility verdict, no summary,
no comparison table — downstream.

## The ten

1. **12A and 80G registration** — number or certificate, not a claim. One
   real exemption to check for: some funders, government PSUs especially,
   exempt Section 8 companies from needing 12A/80G at all. If this
   organisation is a Section 8 company, record that, because whether the gate
   blocks depends on the funder.
2. **Form CSR-1 and the CSR Registration Number.** This is the specific wall
   for Section 135 money: an organisation can hold 12A, 80G, FCRA and
   everything else and still be categorically unable to receive CSR funds
   without it. The filing must be digitally certified by a practising CA, CS
   or Cost Accountant — note whether a professional is named.
3. **Three years of audited accounts, IT returns and annual reports.** Record
   the actual years covered and whether each is findable and public, not
   "audits exist". This is usually the real bottleneck, and it is the gate
   that effort this quarter cannot fix — flag it explicitly even when 1 and 2
   are clean.
4. **Three years of similar work, evidenced by documents** — MoU, Work Order
   or Completion Certificate. A self-declared track record is `claimed`. "We
   have worked in this sector for years" with no document attached is not
   this field being satisfied.
5. **Registration certificate, MoA, trust deed or bye-laws.** Record the exact
   registration type — society, trust, or Section 8 company — and whether a
   certificate not in English has a translated copy available, which some
   funders require explicitly.
6. **PAN, and DARPAN ID checked against blacklist status.** DARPAN is a
   negative-check key, not just an ID to copy down. Some funders bar engaging
   any organisation blacklisted there, so check the status where a lookup is
   possible; recording the ID as present is not checking it.
7. **Governing board** — member count, whether bios or work profiles are
   published, and any conflict-of-interest exposure such as a board member
   with dealings at a funder the organisation is approaching.
8. **Permanent staff and technical capacity** — headcount of permanent staff,
   not contractors or volunteers, and whether sector-specific technical staff
   are evidenced. Some funders bar sub-contracting outright and require the
   capacity in-house.
9. **Financial profile** — three-year revenue, donor concentration (is the
   funding dependent on a small number of donors; some funders reject that),
   whether a dedicated bank account exists, and whether a practising CA's
   "no profit no loss" certificate exists where required.
10. **Institutional policies**, the category no registration-number checklist
    covers: child safeguarding policy or a written commitment to develop one,
    HR and remuneration policy, finance and procurement policy, an organogram,
    recent board minutes, a feedback and grievance mechanism, and monitoring
    systems. Record which are published and which are absent. Never infer one
    from the organisation's size or maturity.

## FCRA is not part of this chain

FCRA governs foreign contribution and is orthogonal to CSR and domestic-grant
eligibility. Record it as its own field when the organisation also seeks
foreign money, but its presence or absence does not move the CSR answer.

## Two things to confirm before anything else

**It is the right organisation.** Namesakes are common. Confirm against the
organisation's own materials before any budget is spent.

**Where it actually works.** Registered in one state and operating mainly in
another is common enough to check for explicitly, from the organisation's own
materials rather than from whatever state a prior list assumed.

## What this skill does not do

It does not produce an eligibility verdict, score the organisation, rank a
list or lay out a comparison. It does not write to the catalog. It produces
ten cited fields per organisation and stops.
