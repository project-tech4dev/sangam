# Theme taxonomy in Postgres: `tags` plus one join table

## Context
The taxonomy (3 domains → 11 themes → 48 sub-themes, 4 lenses, with SDG / Schedule VII / scheme links) exists
only as JSON in `frontend/features/taxonomy/data/themes.json`. We store it in the existing `tags` table — one row
per *thing* — and add one join table, `tag_links`, for every *connection* between two tags, so links are real
foreign keys instead of JSON.

## How each part of `themes.json` is stored

### 1. 3 domains → 11 themes → 48 sub-themes = 62 `tags` rows, tree via `parent_id`
| kind | code | label | parent_id |
|---|---|---|---|
| domain | livelihoods | Livelihoods | — |
| theme | skilling | Skilling for jobs & employment | → Livelihoods |
| sub_theme | vocational-foundational | Vocational & foundational skilling | → Skilling |

`status` = the domain's active/draft (copied to its themes); `description` = domain `source`; `sort_order` = JSON order.

### 2. Each sub-theme's SDGs, Schedule VII clause, schemes = `tag_links` rows
The things linked *to* become `tags` rows once:
| kind | how many | example (code / label) |
|---|---|---|
| sdg | 17 (from `common.json`) | `4` / Quality Education |
| csr_sector | 12 — **already seeded** by `seed_schedule_vii` | `ii` / Education, vocational skills… |
| scheme | 54 distinct | `pmkvy-skill-india` / PMKVY (Skill India) |

Then each sub-theme gets one link row per reference:
| tag_id | linked_tag_id | note |
|---|---|---|
| Vocational & foundational skilling | SDG 4 | |
| Vocational & foundational skilling | SDG 8 | |
| Vocational & foundational skilling | Schedule VII (ii) | Vocational Skills ← the MCA sector name |
| Vocational & foundational skilling | PMKVY (Skill India) | |

Totals across 48 sub-themes: **85 SDG links, 65 CSR links, 61 scheme links.**

### 3. 4 lenses = 4 `tags` rows (kind `lens`, no parent) + 4 links
| kind | code | label | link |
|---|---|---|---|
| lens | women_girls | Women & girls | → SDG 5 |
| lens | tribal_remote | Tribal & remote areas | → SDG 10 |
| lens | digital | Uses digital tools | → SDG 9 |
| lens | climate_smart | Climate-smart | → SDG 13 |

Lenses are cross-cutting: they are not under any domain. Applying one to an org is a normal `org_tags` row.

Plus 10 `population` rows from `common.json` (`women`, `tribal-communities`, …) — no links.

**Naming:** `slug` (unique across the table) = `<kind>-<code>`, e.g. `sdg-4`, `sub_theme-vocational-foundational`.
You read `kind` + `code`; `slug` is just the upsert key. A link's meaning comes from the linked row's `kind`
(link to an `sdg` = "reports to"), so `tag_links` has no relation column.

## Changes
1. **`db/migrations/0030_tag_links.sql`**
   ```sql
   CREATE TABLE tag_links (
     tag_id        bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
     linked_tag_id bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
     note          text,
     PRIMARY KEY (tag_id, linked_tag_id)
   );
   CREATE INDEX tag_links_linked_idx ON tag_links (linked_tag_id);
   -- widen tags_kind_check: add 'sub_theme', 'lens'
   ```
2. **Source data**: copy `themes.json`, `common.json` to `seed/data/taxonomy/` (beside `schedule_vii.json`);
   point `scripts/smoke.sh`'s copy check there.
3. **`seed/taxonomy_seed.py`**: after `seed_schedule_vii`, add `seed_vocabularies` (sdg, scheme, population, lens),
   `seed_tree` (domain → theme → sub_theme, parents first), `seed_links` (delete-then-insert links for the
   taxonomy's own tags, so removed references disappear). Same `INSERT … ON CONFLICT (slug) DO UPDATE` pattern.
   Raise if a referenced SDG/clause/scheme can't be resolved. Tree rows that vanish from the JSON →
   `status='deprecated'`, never deleted.
4. **`backend/app/agent/tools/sql/catalog.py`**: add a `tag_links` Table entry (adding a table is a security
   decision — this one holds only vocabulary); add `sub_theme`, `lens` to `tags.kind` values; describe the tree.
5. **Tests**: integration test runs the seed twice and asserts counts
   (3 / 11 / 48 / 4 lenses / 17 / 54 / 10 rows; 85 / 65 / 61 / 4 links); unit test that every SDG/clause in
   `themes.json` resolves.

Out of scope: moving `0022`'s `meta->>'maps_to'` sector→clause crosswalk into `tag_links`, and linking the
existing ~41 `sector` tags to sub-themes — both natural next steps on the same table. Frontend keeps reading the JSON
until a `GET /taxonomy` follow-up.

## Verification
- `make migrate && make taxonomy-seed` twice; `make psql`:
  `SELECT kind, count(*) FROM tags GROUP BY 1;` and
  `SELECT k.kind, count(*) FROM tag_links l JOIN tags k ON k.id = l.linked_tag_id GROUP BY 1;`
- Sub-themes under clause (ii):
  `SELECT t.label FROM tag_links l JOIN tags t ON t.id=l.tag_id JOIN tags c ON c.id=l.linked_tag_id WHERE c.kind='csr_sector' AND c.code='ii';`
- `cd backend && pytest -m integration && ruff check .`; backend boots (`verify_against_db()` passes); `make smoke`.

## Numbering
`0030`, not `0022`: open branches already claim `0022`–`0029` (access/RLS, matching-engine, user-settings).
The runner applies in filename order and tolerates gaps.
