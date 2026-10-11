---
name: catalog-mapping
description: Use when research has been pulled for an organisation and the next question is what of it the catalog can hold and how it compares to what is already there. Says which table and column each pulled field lands in, which fields have no column at all, and how to classify every value against what we already hold — new, confirms, conflicts, supersedes, or no home. Read this before promoting, so the comparison exists before anything is written. Not for deciding what to research, and not for reporting what landed after a write.
---

# Mapping what was pulled onto what we hold

Two steps, in this order, and the first is not optional: **read what the
catalog already holds before classifying anything.** For a funder whose
research is saved, `compare_with_catalog(slug)` does the classifying in code,
row by row, against the same keys the writer uses: start from it, and use the
headings below to explain its five groups rather than to redo them. Otherwise
`funder_dossier(name, entity_kind=…)` returns what is held, per concept, with
the years already covered.
Classifying a pulled value without that read produces duplicates, and
duplicates in a catalog read as corroboration.

## Classify every pulled value as exactly one of these

- **new** — nothing held for this field. Writable.
- **confirms** — held, same value. Not a write; it is a second citation, and
  worth recording as one. Two independent sources agreeing is a stronger fact
  than one source twice.
- **conflicts** — held, different value. **Never resolve this silently.**
  Report both, with both sources, and say which is stronger and why. The
  precedence is the writer's, by source type: registry = manual check > the
  organisation's own document > a funder's > a staff dataset > prior research
  > an aggregator > the seed. Equal sources that disagree are a conflict,
  never a choice; within one source type, more recent beats older only when a
  person decides it. A newer claim does not beat an older certificate.
- **supersedes** — the held value is stale rather than wrong: a registration
  re-issued, a later fiscal year, an `is_current=false` identifier. The old
  row stays, marked superseded; it is history, not an error.
- **no home** — the value is real, cited, and the schema has nowhere to put
  it. Name the field. This is the most important of the five, because it is
  the only one that silently disappears if it is not said out loud.

## Where each field lands

**An NGO's fields.** These land, with one rule that changes what the map
means: every value carries its source type and evidence tier, and on an
organisation the catalog already holds a blank is always filled, a strictly
stronger source replaces a weaker one, and anything else that differs is
**reported as a conflict, never applied** — so a cell in this map can be
correct, cited, and still not become the stored value. Say which. A row a
person entered has no tier and is never overwritten.

| Pulled | Lands in |
|---|---|
| 12A, 80G | `org_identifiers` (`id_type` 12a, 80g) |
| CSR-1 and its number | `org_identifiers` (`id_type` csr1) |
| PAN, DARPAN | `org_identifiers` (`id_type` pan, darpan) |
| whether any of the above is applied for, registered, expired, cancelled, suspended, or could not be checked | `org_identifiers.status` on the identifier's own row — `applied` (a Form 10AB acknowledgement, `application_ref`), `registered`, `expired`, `cancelled`, `suspended`, `not_found`, `check_blocked` (never means valid), with `valid_until` when stated |
| three years of audited accounts | `org_financials.is_audited` per year, plus a `documents` row each |
| registration type and date | `orgs.legal_form` (free text), `orgs.registration_date` |
| the deed, MoA or bye-laws themselves | `documents` |
| three-year revenue | `org_financials.total_income` per year |
| foreign contribution unspent at year end | `org_financials.foreign_unspent` |
| website, description, other spellings of the name | `orgs.website`, `orgs.description`, `orgs.aliases` (a spelling another organisation answers to is held) |
| programme and non-programme spend, foreign contribution | `org_financials` |
| where it works | `org_locations` with `role`, plus `locations` |
| programmes, reach, people | `programs`, `metrics`, `contacts` |
| what a programme works on, for whom | `program_tags` (themes, populations, lenses from the taxonomy) |
| the focus it states for itself | `org_tags` |
| **three years of similar work evidenced by MoU / Work Order / Completion Certificate** | **no home** |
| **governing board: size, published bios, conflict of interest** | **no home** |
| permanent staff count, with what was counted | `orgs.staff_count`, `orgs.staff_count_note` |
| **technical capacity** | **no home** |
| **donor concentration, dedicated bank account, no-profit-no-loss certificate** | **no home** |
| **institutional policies — safeguarding, HR, finance, organogram, board minutes, grievance, monitoring** | **no home** |

**A funder's fields.**

| Pulled | Lands in |
|---|---|
| receiving legal entity, and its parent | `funders.name`, `funders.parent_id` |
| district-level geography | `funder_locations` with `role`, plus `locations` |
| CSR position by year | `funder_csr_years` |
| project and sector spend | `funder_activity`, `kind='spend'`, with `domain_tag_id` / `theme_tag_id` inferred and `classified_by`, `classification_note` saying from what |
| implementing partners, and what each received in a year when stated | `funder_activity`, `kind='partner'`, with `amount` (INR) |
| the funder's own programme split | `funder_activity`, `kind='programme'` — never summed with spend lines |
| the funder's standing eligibility — statutory restatement, its own bar, disqualifiers | one `documents` row, `doc_type='funder_eligibility'`, the text verbatim under three headings, per page |
| CIN and other names it files under | `funders.cin`, `funders.aliases` |
| its stated focus areas and who it funds for | `funder_tags` (themes, populations, lenses from the taxonomy) |
| open call, its deadline, amount band | `rfps` |
| a requirement printed in *that call* | `rfps.eligibility` — jsonb, so it stores the text and queries none of it. Not the same claim as the standing bar above; the same sentence in both is two rows, not a duplicate |
| whether a call is open | `rfps.status` |
| source URL, fetch date | the provenance columns every table carries |
| intake route | `funders.intake_mode` |
| **whether an intake route was live when checked** | **no home** — `rfps.url` is one call, not a standing door |
| says it funds external NGOs | `funders.funds_external` (stated) — `funder_activity.implementation_mode` is what it did |
| **the document checklist, verbatim** | **no home** |
| typical duration, grant band | `funders.typical_duration_months`, `grant_size_min`, `grant_size_max` |
| **co-funding share** | **no home** |
| **access state — scanned, soft-404, archived** | **no home** |

## What to produce

Per organisation: every pulled field, its classification, and for `conflicts`
both values with both sources. Then two counts that are the point of the whole
exercise — how many values are writable, and how many are real, cited and
have nowhere to go. The second number is what tells us which migration to
write next.

Produce the comparison. Do not write anything; `promote_research` writes, and
it runs after this.
