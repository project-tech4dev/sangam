# Funder types, India CSR money and FCRA in Funder Match

*2026-11-25 · Draft v1 · issue #324 and its comment · no earlier plan on this subject*

## 1. Goal

**Every funder gets one of nine types that mean the same thing on every screen, and two
facts about its money: whether it is Indian CSR money (`india_csr`) and whether it is
foreign (`money_origin`). Funder Match then asks for CSR-1 and FCRA only when they apply.**

Success means four things a person can check:

| check | today | after |
|---|---|---|
| Funders typed `other` on the shared database | 17 of 46 | 1 (Roots to Branches, to review) |
| A funder's type label on its profile vs its match card | can differ (two label maps) | always the same (one map) |
| A match with Misereor mentions FCRA | never | yes, as a flag and a "what would raise the score" line |
| A US company foundation loaded later is asked for CSR-1 | yes (`SECTION_135_TYPES`) | no: CSR-1 reads `india_csr` only |

Out of scope, and kept for the follow-up issue the comment lists: `external_ids` (EIN and
friends), currency on `funder_activity.amount`, and fiscal-year mapping for foreign grants.
No foreign funder rows load from this plan.

## 2. Blast radius

Built by hand: there is no domain map. Sources: `backend/app/ask/tools/sql/catalog.py`
(the `funders` entry), `CLAUDE.md`'s architecture section, and a repo-wide search for
`funder_type`, `section_135_bound`, `SECTION_135_TYPES` and the old type values.

| surface | hop | why affected | status | notes |
|---|---|---|---|---|
| `funders.funder_type` | 0 | new vocabulary, CHECK, remap | in scope | M1 |
| `funders.money_origin` | 0 | new column | in scope | M1 adds it, M4 uses it |
| `funders.funder_group` | 0 | new generated column: the five-way roll-up | in scope | M1 |
| `funders.section_135_bound` | 0 | renamed `india_csr`, backfilled | in scope | M2 |
| `csr_years.section_135_applicable` | 1 | different field: whether the law applies to a company in a year | unaffected | keeps its name |
| SQL catalog `funders` entry | 1 | both agents' `db_query` sees the new columns | in scope | catalog drift raises at boot, so it changes in the same PR as each migration |
| `matching/rules.py::eligibility` | 1 | CSR-1 gate, FCRA item | in scope | M2, M4 |
| `repositories/matching.py` | 1 | loads `FunderProfile` | in scope | M2, M4 |
| `proposals/gates.py`, `routes/proposals.py`, `repositories/proposals.py` | 2 | Pitch step 1 lists CSR-1 from the same rule | in scope | M2, M4 |
| `repositories/funders.py`, `routes/funders.py` (`section_135` filter), `schemas/funders.py` | 2 | REST list filter and field | in scope | M2 renames the param to `india_csr` |
| `repositories/profile_facts.py`, `schemas/profiles.py` | 2 | profile identity | in scope | M2, M3 |
| `repositories/registry.py`, `schemas/registry.py` | 2 | Registry type facet and filter | in scope | M3 filters on `funder_group` and `money_origin` |
| `repositories/funder_matches.py`, `routes/funder_matches.py`, `schemas/funder_matches.py` | 2 | match card carries `funder_type` | in scope | M3 adds `money_origin` |
| `ask/tools/matching_tools.py` | 2 | prints the raw type after a funder name | in scope | M3 prints the label |
| Import: `research/finding_types.py` `IdentityFinding` | 1 | the type Literal and the flag | in scope | M1, M2; `money_origin` in M4 |
| Import: `research/contract.py` expectations | 1 | a save must give a finding or a gap per field | in scope | M4 adds `money_origin` |
| Import: `catalog/promote_records.py`, `rows.py`, `writer_funder.py`, `tools/catalog_tools.py` | 1 | write and read the fields | in scope | M1, M2 |
| Import: `skills/research/funder-intake-research/SKILL.md`, `skills/entity-record/SKILL.md`, `prompts/entity_researcher.md` | 1 | tell the researcher the values | in scope | M1, M2, M4 |
| Saved `entity_research` briefs | 1 | hold old type values and `section_135_bound` | in scope | promote maps old keys when it reads them (see LLD) |
| Saved Funder Match runs (`funder_matches`) | 2 | `detail` was judged under the old rule | deferred | not rerun automatically; staff note in CHANGELOG |
| `seed/seed.py`, `seed/data/rubrics/funders.json`, `seed/graph_seed.py` | 1 | write the old names | in scope | M1, M2 |
| Neo4j graph | 2 | `graph_seed` text says "Section-135-bound" | in scope | text only, rebuilt by `make graph-seed` |
| `frontend/lib/format.ts` `FUNDER_TYPES` and `features/ask/views/funder-match/funderType.ts` | 2 | two label maps | in scope | M3 makes one |
| `FunderMandate.tsx`, `RegistryClient.tsx`, `FunderMatchView.tsx`, `MatchCard.tsx`, `rows.ts`, `lib/api/types.ts` | 2 | labels, filters, the Section 135 row | in scope | M2, M3 |
| `ingest/catalog/review.py` (enum code as words) | 2 | humanises any code | unaffected | generic |
| Design system "Sangam Design System v2" | 2 | Registry, profile and Funder Match labels and filters change | in scope | M2, M3 sync the UI kit |
| `docs/entities/*.md` | 2 | old briefs printed as Markdown | unaffected | historical records, not read by code |
| News source key `india_csr` (`ingest/data/sources/funders.json`) | – | same word, different namespace | unaffected | parked adapter; noted in risks |
| `openwiki/` | – | generated | in scope | offer `make wiki-update` per PR (paid, ask first) |

## 3. High-level design

```
            Scout research                         staff (migration list)
                 │ identity: funder_type, india_csr, money_origin (+ cited source)
                 ▼
  funders ── funder_type  (9 values, CHECK) ──► funder_group (generated: CSR/HNI/Philanthropy/Govt./Other)
          ├─ india_csr    (true | false | NULL) ─► CSR-1 item ┐
          └─ money_origin (domestic|foreign|mixed|unknown) ──► FCRA item ┤
                                                                       ▼
                       rules.py::eligibility (pure) ── flag, never fail ── match card + Pitch step 1
                                                                       │
  frontend/lib/funderTypes.ts (ONE label map) ◄── Registry · profile · Funder Match filters
```

Agent architecture, with the changed parts marked `*`:

```
Ask Sangam ── db_query* (catalog: funder_group, money_origin, india_csr)
           └─ compare_fit ── repositories/matching.py* ── rules.py* (CSR-1 on india_csr, FCRA)
Scout ── entity-researcher ── save_research ── contract.py* (money_origin expected, M4)
      └─ catalog-writer ── promote_records.py* ── writer_funder.py*
```

Touched: Postgres (three migrations), the SQL catalog, Ask's matching tool output, Scout's
research schema and skill. Not touched: Neo4j beyond seed text, Supabase Storage, models.

**The key trade-off: where the roll-up lives.**

> **The rule:** the five-way roll-up is a generated column in Postgres, not a second map in TypeScript.
> **Example:** Priya filters the Registry to "Philanthropy"; the SQL filters `funder_group = 'philanthropy'`, and Ask answers "how many philanthropy funders" with the same column.
> **Why it matters:** two maps of the same thing is the bug this issue was filed for.

Labels (the words a person reads) stay in one frontend module, because only the screen shows them.

## 4. Low-level design

### Migrations

Open PRs hold `0058`–`0063`, so this plan takes `0064`–`0066`. Renumber at merge if any of those land first under a different number.

**`0064_funder_types.sql` (M1)**

- Drop nothing. Map old values: `corporate_csr` → `csr_company`, `corporate_foundation` → `csr_foundation`, `family_trust`, `family_trust_network` → `private_foundation`. Copy each old value into `profile->>'source_funder_type'` first, so Tata Trusts keeps "family trust network".
- Then apply the reviewed list below by `slug`. Any slug the list names that the database lacks is skipped, not an error, so a local database works too.
- `funder_type` stays nullable (NULL means not researched) with `CHECK (funder_type IN (...nine...))`.
- `money_origin text NOT NULL DEFAULT 'unknown' CHECK (money_origin IN ('domestic','foreign','mixed','unknown'))`. Its source goes in `profile->>'money_origin_source'`.
- `funder_group text GENERATED ALWAYS AS (CASE funder_type WHEN 'csr_company' THEN 'corporate' ... END) STORED`, values `corporate | hni | philanthropy | govt | other`, NULL when the type is NULL.

The reclassification list (shared database, 2026-11-25). Every row is for review before M1 merges.

| slug | new `funder_type` | `money_origin` | source for origin | note |
|---|---|---|---|---|
| 12 `corporate_csr` rows | `csr_company` | unknown | – | J.P. Morgan India is foreign-owned: origin waits for the legal rule. The row named "Bharti Infratel Limited merger with Indus Towers…" is a bad name, not a type problem: separate fix |
| 9 `corporate_foundation` rows | `csr_foundation` | unknown | – | EdelGive marked for review (issue) |
| `ashraya-hastha-trust`, `tata-trusts` | `private_foundation` | unknown | – | old value kept in `source_funder_type` |
| `brot-f-r-die-welt-bread-for-the-world` | `international_agency` | foreign | brot-fuer-die-welt.de | |
| `dreik-nigsaktion-der-katholischen-jungschar-sterreichs-dka` | `international_agency` | foreign | dka.at | |
| `katholische-frauenbewegung-sterreichs-kfb` | `international_agency` | foreign | teilen.at | |
| `misereor` | `international_agency` | foreign | misereor.org | |
| `terre-des-hommes-deutschland-e-v` | `international_agency` | foreign | tdh.de | |
| `stichting-liliane-fonds` | `international_agency` | foreign | lilianefonds.org | |
| `global-greengrants-fund` | `intermediary` | foreign | greengrants.org | |
| `women-s-fund-asia` | `intermediary` | foreign | womensfundasia.org | |
| `the-resilience-fund-for-women-in-global-value-chains` | `intermediary` | foreign | resiliencefundforwomen.org | |
| `paul-hamlyn-foundation` | stays `private_foundation` | foreign | phf.org.uk | |
| `stiftung-childaid-network` | stays `private_foundation` | foreign | childaid.net | |
| `mariwala-health-foundation`, `rajiv-gandhi-foundation`, `selco-foundation` | `private_foundation` | unknown | – | SELCO may be an operating foundation: check `funds_external` |
| `caring-friends` | `hni` | unknown | – | a giving network |
| `ekaimpact-social-foundation` | `intermediary` | unknown | – | to review |
| `impact-foundation-india` | `intermediary` | unknown | – | its website is dasra.org: to review |
| `childline-india-foundation` | `government` | unknown | – | to review (issue) |
| `roots-to-branches-foundation` | `other` | unknown | – | to review: nothing fits yet |

> **The rule:** the migration sets `money_origin` only where the list names a source; everything else stays `unknown`.
> **Example:** Misereor becomes `foreign` with `misereor.org` as its source; J.P. Morgan India stays `unknown` until the legal rule says how a foreign-owned Indian company counts.
> **Why it matters:** a guessed origin would put a wrong FCRA line on a real NGO's match.

**`0065_india_csr.sql` (M2)**

- `ALTER TABLE funders RENAME COLUMN section_135_bound TO india_csr`.
- Backfill on `funder_type IN ('csr_company','csr_foundation')`: NULL → true; false → NULL (re-check, as decided). Today that turns Reliance Foundation and SBI Foundation from false to NULL, so their matches say "Not judged" until someone records a source.
- RLS: policies name columns only through `SELECT` grants; the rename carries them. `test_agent_rls.py` confirms `authenticated` can still read the column.

**`0066` (M4) is not needed**: the FCRA rule reads `money_origin` from 0064 and `org_identifiers` rows that already exist (11 `fcra` rows registered on the shared database).

### SQL catalog (`ask/tools/sql/catalog.py`)

A security decision: these are columns on a table both agents already read, so no new rows become reachable. The notes:

- `funder_type`, `values=` the nine, note "NULL means not researched".
- `funder_group`, `values=` the five, note "the roll-up the Registry filters on".
- `money_origin`, note "whether the money an NGO receives counts as foreign under FCRA; 'unknown' is not 'domestic'".
- `india_csr`, note "true: the money counts as Section 135 CSR spend, so the NGO needs CSR-1. NULL means unknown, not false".

### Funder Match (`app/matching/`)

- `rules.py`: delete `SECTION_135_TYPES` and `UNTYPED`. `FunderProfile` gains `india_csr` (renamed) and `money_origin`.
- CSR-1: `india_csr is True` → item; `None` → not judged line "CSR-1: whether this funder's money is Indian CSR isn't recorded."; `False` → no item.
- FCRA (M4): `money_origin == 'foreign'` → `items["fcra"] = _credential("fcra", org, today)`; `mixed`/`unknown` → not judged "FCRA: whether this funder's money is foreign isn't recorded."; `domestic` → no item. `ITEMS["fcra"] = ("FCRA", "Record the FCRA registration")`.
- No new failure state: held counts, missing lowers points pro rata, unreadable is left out. This is what `_credential` already does.

> **The rule:** FCRA is a flag, never a disqualifier.
> **Example:** KABIL has no FCRA row. Its match with Misereor drops from 20 to 15 eligibility points, the card says "FCRA not on record", and "Record the FCRA registration (up to 5 points)" appears under what would raise the score.
> **Why it matters:** a missing row usually means Scout did not find it, not that KABIL lacks it.

### Pitch step 1 (`proposals/gates.py`)

`build(detail, india_csr, money_origin)`. CSR-1 shows when `india_csr` is true; FCRA (M4) when `money_origin == 'foreign'`, with `REQUIREMENTS["fcra"] = ("FCRA registration", "Registered under FCRA to receive foreign contributions")`. Whether FCRA is `hard` (a No stops the proposal) is an open question below.

### REST

No new endpoint. Changed fields only:

- `GET /api/funders?india_csr=` replaces `?section_135=` (`routes/funders.py`, `repositories/funders.py`).
- `schemas/funders.py`, `schemas/profiles.py`, `schemas/registry.py`, `schemas/funder_matches.py` gain `money_origin` and `funder_group`, and rename the flag.
- Registry: `?ftype=` filters `funder_group`; new `?origin=` filters `money_origin` (`repositories/registry.py` facet counts by `funder_group` and `money_origin`).

### Import (Scout)

- `IdentityFinding.funder_type` Literal becomes the nine values; `india_csr: bool | None`; `money_origin` Literal plus `money_origin_source` in M4.
- `promote_records.py` reads old saved briefs: `ident.get("india_csr", ident.get("section_135_bound"))`, and maps the four old type values. This is a reader for stored data, not a re-export: briefs saved before this change still promote correctly.
- `contract.py` (M4): funder identity expects `money_origin`, so a save gives a cited value or a gap such as "not stated".
- `funder-intake-research/SKILL.md`: the nine types with one example each, the `india_csr` definition, and (M4) how to find `money_origin` (the funder's own "about" page, its registered country, an FCRA donor listing).

### Frontend

- New `frontend/lib/funderTypes.ts`: `funderTypeLabel`, `funderGroupLabel`, `moneyOriginLabel`. `lib/format.ts` and `funderType.ts` re-point to it and lose their maps (M3).
- Labels: "Corporate · run by the company", "Corporate · through its foundation", "Private or family foundation", "Individual or giving network", "Re-granting fund or intermediary", "International development or church agency", "Bilateral or multilateral donor", "Government or statutory body", "Other". Groups: "Corporate", "HNI", "Philanthropy", "Govt.", "Other".
- `FunderMandate.tsx`: "India CSR funder · Yes / No" (M2); "Money · Foreign" when foreign (M3), "· needs FCRA" added in M4.
- Registry and Funder Match: the type filter shows groups; a second `FilterRow` dropdown "Foreign / Domestic" (M3), per the list-page pattern in `components/ui/ListPage.tsx`. Styles go in classes, not inline.

### Docs

- `docs/FUNDER_TYPES.md` (M1): the nine types, the roll-up, `source_funder_type`, and the comment's foreign-source mapping table (Kindora, Candid, IRS labels → our types).
- `docs/FCRA.md` (M4, before code): the legal rule `money_origin` follows, signed off.
- `ARCHITECTURE.md`: the CSR-1 and FCRA rules in the Funder Match section. CHANGELOG line per PR.

## 5. Security review

- **Auth:** no new endpoint. The renamed filter and new fields ride existing routes, which already run as the caller under RLS (`PoolDep`).
- **Validation:** the CHECK constraints are the real guard; Pydantic `Literal`s mirror them at the Import boundary, and the registry `?origin=` param is a `Literal` too, never interpolated.
- **Catalog exposure:** three columns on `funders`, which both agents already read. None holds personal data. `profile` stays `heavy` and its new keys (`source_funder_type`, `money_origin_source`) hold URLs and codes only.
- **Writes:** the reclassification runs once in a migration as the owner; `make migrate ENV=staging` stays a deliberate, backed-up step.
- **Legal correctness** is the real risk, not a security one: hence `docs/FCRA.md` gates M4.

## 6. Testing

Unit tests touch no database: `rules.py` and `gates.py` are pure; routes use `client_for(...)` with a monkeypatched repository.

| test | file | milestone |
|---|---|---|
| Each old value maps to the right new type; unknown values are refused by the CHECK | `tests/test_migration_integrity.py` (integration) | M1 |
| `funder_group` per type, NULL type → NULL group | integration | M1 |
| Catalog lists the new columns and values (`verify_against_db` passes) | `test_sql_integration.py` (integration) | M1, M2 |
| An old saved brief with `section_135_bound` and `corporate_csr` promotes to `india_csr` and `csr_company` | `tests/test_promote*.py` | M1, M2 |
| `india_csr=True` adds CSR-1; `None` → listed in `not_judged`, not counted; `False` → no item | `tests/test_matching_rules.py` | M2 |
| A US company foundation (`csr_foundation`, `india_csr=False`) gets no CSR-1 item | same | M2 |
| Backfill: corporate NULL → true, corporate false → NULL, non-corporate untouched | integration | M2 |
| Gates: CSR-1 requirement follows `india_csr` | `tests/test_gates.py` | M2 |
| One label per type on Registry row, profile and match card | Vitest `funderTypes.test.ts` | M3 |
| Registry `?ftype=philanthropy` and `?origin=foreign` | route test, monkeypatched repo | M3 |
| FCRA: foreign + held → counts; foreign + missing → fewer points, card line, improve line, never `fail`; foreign + `check_blocked` → left out; mixed/unknown → `not_judged`; domestic → no item | `tests/test_matching_rules.py` | M4 |
| Contract: a funder save without `money_origin` and without a gap is refused | `tests/test_research_contract.py` | M4 |

Zero means unrecorded: `money_origin = 'unknown'` must never read as domestic, and `india_csr` NULL must never read as false. Both have a test above.

## 7. Milestones

Stacked PRs, one per milestone; stop for review after each. Each frontend milestone is browser-tested per role and at phone width before the next.

#### Milestone 1: the nine types, the roll-up and `money_origin`
- **Deliverable**: every funder has a valid type and a group; Misereor and ten others read `foreign`; screens look the same as today, except the 16 former `other`s now show real types.
- **Touches**: db, backend (catalog, Import schema and promote, seed), frontend (both existing maps learn the new values), docs.
- **Key tasks**: [ ] `0064_funder_types.sql` with the reviewed list [ ] catalog entries [ ] `IdentityFinding` Literal, promote mapping, skill table [ ] `rules.py` temporarily keeps CSR-1 on `csr_company`/`csr_foundation` so matching is unchanged [ ] seed files [ ] `docs/FUNDER_TYPES.md` [ ] CHANGELOG
- **Acceptance criteria**: `cd backend && pytest && pytest -m integration`; on local, `SELECT funder_group, count(*) FROM funders GROUP BY 1` shows no NULL group for a typed funder.

#### Milestone 2: `india_csr` and CSR-1 on it alone
- **Deliverable**: CSR-1 follows `india_csr`; NULL shows "Not judged"; the profile row reads "India CSR funder · Yes / No".
- **Touches**: db, backend (matching, gates, repositories, schemas, routes, Import), frontend (`FunderMandate`, types), design system.
- **Key tasks**: [ ] `0065_india_csr.sql` with the backfill [ ] every reference renamed, `section_135` param renamed [ ] delete `SECTION_135_TYPES`, `UNTYPED` [ ] skill and prompt wording [ ] design system sync for the profile row
- **Acceptance criteria**: `pytest -k "eligibility or gates or promote"`; `git grep section_135_bound -- backend/app frontend seed` returns only the promote reader for old briefs.

#### Milestone 3: one label map, neutral labels, group and origin filters
- **Deliverable**: one type label everywhere; "Corporate" replaces "CSR" in labels and filters; Registry and Funder Match filter by group and by Foreign / Domestic.
- **Touches**: frontend, backend (registry facets, match card field, `matching_tools` label), design system.
- **Key tasks**: [ ] `lib/funderTypes.ts`, delete the two old maps and the dead labels [ ] Registry `?ftype=` on `funder_group`, new `?origin=` [ ] Funder Match filters [ ] UI kit pages for Registry, profile and Funder Match
- **Acceptance criteria**: `cd frontend && npm test && npm run build`; Chrome: Registry filtered to "Philanthropy" and "Foreign" shows the six agencies, the three funds, Paul Hamlyn and Childaid.

#### Milestone 4: FCRA in Funder Match and Pitch (after `docs/FCRA.md` is signed off)
- **Deliverable**: a foreign funder's match asks for FCRA as a flag; Pitch step 1 lists it; Scout researches `money_origin` with a source.
- **Touches**: docs, backend (rules, gates, contract, skill), frontend (profile "· needs FCRA").
- **Key tasks**: [ ] `docs/FCRA.md` signed off [ ] FCRA item and `ITEMS` [ ] gates requirement [ ] `money_origin` in `IdentityFinding`, contract and skill [ ] CHANGELOG note that saved runs are not rerun
- **Acceptance criteria**: `pytest -k "fcra or eligibility or contract"`; `make match ORG=kabil` on local shows an FCRA line on Misereor's card.

## 8. Open questions and risks

1. **Is FCRA `hard` in Pitch step 1?** CSR-1 is (a No stops the proposal, because it is law for Section 135 money). FCRA is also law for foreign money. Recommend: hard in Pitch, flag in matching, decided in `docs/FCRA.md`.
2. **The reclassification list needs a human pass**, especially the six "to review" rows (EdelGive, CHILDLINE, Ekaimpact, Impact Foundation/Dasra, Roots to Branches, SELCO).
3. **`public_sector` flag** for BEML, BEL and IRCTC (government CSR guidelines): the issue leaves it open. Recommend: not in this plan.
4. **`not_available` status** on one org's `fcra` row is read as "missing" by `_credential` today. It should probably be "unreadable"; check what Scout means by it before M4.
5. **Migration numbers** `0058`–`0063` are held by open PRs (#428 to #470); renumber at merge if needed.
6. **Same word, two meanings:** `india_csr` is also a parked news source key. Different namespaces, no clash in code, but a reader of `ingest_runs.requested_sources` may confuse them. Acceptable; noted in `FUNDER_TYPES.md`.
7. **Saved runs** keep the old eligibility until someone reruns them. `make match` reruns all for free (no model).
8. **Deploying M1 before M2** leaves `section_135_bound` live for one release; nothing breaks, since M1 keeps the current CSR-1 behaviour.
