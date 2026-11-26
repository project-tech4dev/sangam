# Funder types and where the money comes from

Two fields on `funders`, set by migration `0064` (#324) and checked by the database.

## `funder_type`: what kind of funder

| Value | Label | `funder_group` | Example |
|---|---|---|---|
| `csr_company` | Corporate · run by the company | `corporate` | ITC, TCS, IRCTC |
| `csr_foundation` | Corporate · through its foundation | `corporate` | Infosys Foundation, HCL Foundation |
| `private_foundation` | Private or family foundation | `philanthropy` | Azim Premji Foundation, Tata Trusts |
| `hni` | Individual or giving network | `hni` | Caring Friends |
| `intermediary` | Re-granting fund or intermediary | `philanthropy` | Global Greengrants Fund, Women's Fund Asia |
| `international_agency` | International development or church agency | `philanthropy` | Misereor, Brot für die Welt |
| `bilateral_multilateral` | Bilateral or multilateral donor | `govt` | none yet |
| `government` | Government or statutory body | `govt` | CHILDLINE India Foundation (to review) |
| `other` | Other | `other` | only when none fits |

NULL means the type has not been researched. `funder_group` is a generated column, so the roll-up has one definition.

**A type is not the CSR law.** Whether an NGO needs CSR-1 depends on whether the money is Section 135 CSR money, not on
the type: a US company foundation is `csr_foundation` and needs no CSR-1.

## `money_origin`: is the money foreign under FCRA

`domestic`, `foreign`, `mixed` or `unknown` (the default). `unknown` never means domestic. Where it is set, the source
is in `profile->>'money_origin_source'`. The legal rule it follows is still to be written (`docs/FCRA.md`, #324 M4).

Example: Misereor is `international_agency` and `foreign`, with `https://www.misereor.org` as its source.

## Old values and source labels

| Before `0064` | After |
|---|---|
| `corporate_csr` | `csr_company` |
| `corporate_foundation` | `csr_foundation` |
| `family_trust`, `family_trust_network` | `private_foundation`; the old value kept in `profile->>'source_funder_type'` |
| any other value | `other`, the old value kept the same way |

Briefs saved before `0064` still carry old values; promote maps them the same way (`current_funder_type`,
`ingest/catalog/rows.py`). A re-import's `other` never replaces a type already on the row, and in a merge any real
type beats `other`, whatever the source. A type the reviewed list in `0064` replaced is kept in `source_funder_type`
too, and a funder marked foreign there always has its website as `money_origin_source`.

Those reviewed rows carry `profile.funder_type_reviewed`, and no re-import changes their type; staff change it by hand.
`0064` makes the same change to every funder row in Import's undo log (`catalog_writes`), so a save that could be undone before it still can. A save
that wrote one of the reviewed rows cannot, as after any later edit.

## Foreign sources

How a foreign source's own label maps, for when foreign funders load. Keep that label in `source_funder_type`.

| Source label (Kindora, Candid, IRS) | `funder_type` | Note |
|---|---|---|
| Family or independent foundation | `private_foundation` | |
| Operating foundation | `private_foundation` or `other` | `funds_external = false` |
| Faith-based foundation (US) | `private_foundation` | |
| European church or development agency | `international_agency` | |
| Community foundation, DAF sponsor, re-granting public charity | `intermediary` | an Indian intermediary cannot re-grant foreign money (FCRA 2020) |
| Corporate (company-sponsored) foundation | `csr_foundation` | not Indian CSR money, `money_origin = foreign` |
| Corporate giving programme | `csr_company` | same |
| Individual or UHNI | `hni` | |
| Bilateral or multilateral donor | `bilateral_multilateral` | |
| Lotteries, other | `other` | |

`india_csr` is also the key of a parked news source (`ingest/data/sources/funders.json`); the two are unrelated.
