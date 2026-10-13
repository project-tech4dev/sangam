# Import M4: every source is a document

Fourth of the stacked PRs in `2026-10-13-import-researcher-contract.md`, on M3's branch.

## Today
- `fetch_document` archives a PDF; `read_page` archives nothing, so a page a fact rests on can change or vanish.
- A `documents` row exists only when the researcher filed a `document` finding. Example: Axis's facts cite 40
  URLs, and most carry `document_id` NULL.
- `doc_type` is free text: staging has 38 values for some 12 kinds (`csr_report`, `csr_impact_report`,
  `programme_report`, `case_study`…).
- Nothing says which programme or year a document covers.

## What changes
| Change | Example |
|---|---|
| `read_page` archives the text it read, as `<url-hash>/<sha256>-page.md` in `source-archive`, like a PDF | Axis's "Sustainable Livelihoods" page is kept as read on 13 Oct |
| Promotion makes one `documents` row per public source any fact cites, not only `document` findings; type and title come from a `document` finding for that URL when there is one, else `web_page` (an archived page) or `other` | every Axis fact's line gets its `document_id` |
| A fixed `doc_type` list on the finding; an older name maps to its kind, an unknown one to `other` | `csr_report` → `csr_impact_report`; `about_page` → `web_page` |
| `document_links` (migration `0047_document_links.sql`): document → owner, programme, fiscal year, pages used | the SLP impact assessment → Axis · Sustainable Livelihood Programme · FY2022-23 · pp. 12, 34 |
| The brief's "Sources read" lists each source with its type, title, pages used and its `[documents:N]` | `- SLP Impact Assessment · impact_assessment · pp. 12, 34 · [documents:812]` |

### The fixed list
annual_report · csr_annexure · brsr · csr_policy · csr_impact_report · impact_assessment · programme_report ·
audit_report · financial_statements · fcra_return · registration_certificate · trust_deed · exemption_order ·
exemption_application · csr1_approval · fcra_certificate · policy · press_release · news_article · grant_list ·
registry_record · research · web_page · other. The three reserved types keep their own paths, and a Doc
Vault upload keeps whatever type its uploader chose: the list is enforced on research, not as a CHECK.

### `document_links`
One row per (document, owner, programme, fiscal year), with `pages text[]` as facts cite them ('p.33', 'Annexure 4'); exactly one of `org_id` /
`funder_id`. Written at promotion from every fact that was written or confirmed, so a link says "this
document backs these facts". A link to a private document is readable only where the document is
(row security joins through `documents`). Added to the SQL catalog: a security decision, and it exposes
nothing the `documents` row does not.

## Decided
- **Archived copies stay private.** `source-archive` is a private bucket since 0020; staff open a copy
  through a signed URL. The brief links the original; no change.
- **No `page` column on fact tables.** A fact's page is in its brief block and in `document_links.pages`.
- **Existing rows keep their `doc_type`.** M5's backfill re-promotes Axis and KABIL, which re-types theirs.

## Known limits
- A plan (the Gate's dry run) writes no documents and no links, as today.
- A page archived before this PR has no copy; its row has no `storage_path` until it is read again.
- The news verifier reads pages with `read_page` too, so a verified article is archived as well.
- Staging has taken neither 0046 nor 0047: run `make migrate ENV=staging` before this deploys.
- A source's earlier `doc_type` (e.g. KABIL's `other` from a pre-list run) stays until a document finding re-types it; M5's backfill does.

## Verification
- `pytest -m "not integration"`, `ruff`; `make migrate` on a local database.
- Exit: Axis's brief promoted into a local database (Storage writes stubbed): every public source an
  Axis fact cites is a typed `documents` row, every written fact carries its `document_id`, each programme
  fact's document is linked to that programme, and the brief lists them.
