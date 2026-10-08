# Taxonomy domains: Environment and Others — Implementation Plan

> **For agentic workers:** REQUIRED: execute this plan with superpowers:subagent-driven-development — a fresh implementer subagent per task, a fresh reviewer subagent checking each task before the next starts, and a whole-branch review at the end. Do not use executing-plans or implement inline. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Environment and Others to the theme taxonomy as theme-less domains, so every CSR spend line can carry one of five domains, and take every "Draft" label off the `/resources/taxonomy` page.

**Architecture:** The taxonomy's source of truth is `seed/data/taxonomy/themes.json`. `seed/taxonomy_seed.py` (from PR #98) turns it into `tags` rows. The frontend reads a byte-identical copy in `frontend/features/taxonomy/data/`. This PR appends two domains to the JSON, re-copies it, widens the SQL catalog's `tags.domain` note, and changes three frontend files: empty domains show only their `source` line, and no status label appears anywhere. Health and Education move from `status: "draft"` to `"active"`, so no domain is draft; the `status` field stays in the data and in `tags.status`.

**Tech Stack:** Python 3.12 (pytest, psycopg 3), JSON seed files, Next.js 16 / React 19 / TypeScript, bash smoke script.

**Spec:** features-plans/data-model/2026-10-07-funder-model-consolidation.md (§1, decisions D6, D10)

## Global Constraints

- Base branch: `origin/feat/taxonomy-tags` (PR #98, open). The PR for this plan targets `feat/taxonomy-tags`, not `master`.
- Never check out, edit or commit in the main checkout `/Users/vinod/GitHub/sangam`: it is on `master` and serves the running dev site. Fetching and adding a worktree from it is fine; all work happens in the worktree.
- Environment domain JSON, exactly: `{"domain": "environment", "label": "Environment", "status": "active", "source": "Spend on environmental sustainability, conservation and animal welfare that is not a livelihood programme", "themes": []}`
- Others domain JSON, exactly: `{"domain": "others", "label": "Others", "status": "active", "source": "Spend that fits no programme domain: disaster relief, sports, central funds, administration, unlabelled or multi-sector lines", "themes": []}`
- The two domains are appended after `education`, giving `sort_order` 3 and 4. They have no themes, so no sub-themes and no `tag_links`.
- `TAG_COUNTS["domain"]` becomes 5. Every other count is unchanged: `sdg` 17, `population` 10, `scheme` 54, `lens` 4, `theme` 11, `sub_theme` 48, and 211 links.
- The seed writes `domain-environment` and `domain-others` (kind `domain`).
- `frontend/features/taxonomy/data/themes.json` must stay byte-identical to `seed/data/taxonomy/themes.json`. Copy it with `cp`, never edit it by hand.
- The catalog note on `tags.domain` lists five domains: `'livelihoods' | 'health' | 'education' | 'environment' | 'others'`.
- `/resources/taxonomy` renders all five domains. Environment and Others show only their one-line `source` and no theme cards.
- The section index ("In this article") lists all five domains.
- No visible "Draft" or "draft" remains on `/resources/taxonomy`. That covers the badges on domain headings, the status tags in "How the taxonomy works", the `(draft)` index labels, and the "programme-areas draft" wording inside the Health and Education `source` strings.
- No domain is draft: Health and Education's `status` becomes `"active"`, like the other three. The `status` field stays in the JSON, in `tags.status`, and in the frontend type, which is left as `Domain.status: "draft" | "active"` (unchanged, so `tsc` stays green and nothing else needs touching).
- The two `source` strings lose only the word: "programme-areas draft, regrouped" becomes "programme areas, regrouped". No other rewording.
- Design system: only `--fs-*` sizes and existing classes and components (`Tag`, `.muted`, `.measure`, `.card`). No new tokens.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **"Draft" leaking through data, not code.** The Health and Education `source` strings say "programme-areas draft", and `DomainSection` renders `{domain.source}` verbatim; their `status` is `"draft"`. Removing the badges alone leaves "draft" on the page and in `tags`. The checks:
   - two backend tests, `test_no_domain_source_says_draft` and `test_no_domain_is_draft` (Task 4), check the data;
   - a frontend visible-text check on the built HTML (Task 4) checks the page;
   - a smoke `check_lacks` (Task 5) checks the live site.

   The page checks strip `<script>` first. `DomainSection` is a client component that receives the whole domain object, so the RSC payload carries raw data that is never shown; the checks are about what a reader sees.
2. **The empty-domain rendering path.** With `themes: []`, the current `DomainSection` prints "0 themes, 0 sub-themes." and an empty card container. The fix is in Task 3, and the built-HTML check asserts that no " 0 themes" text and no `class="card"` appear inside `#environment` or `#others`.
3. **The seed copy and the frontend copy drifting apart.** `make smoke` notices only against a running stack. Task 1 adds a byte-equality pytest (`test_frontend_copy_matches_seed_file`) that fails in CI before smoke ever runs. A `json.dump` round-trip would also silently re-escape the file, so Task 1 inserts the new text and checks `git diff --numstat` (14 added, 0 deleted).
4. **A domain tag with no children going wrong in the seed.** The risks are a parent or link on a childless root, the wrong `status` or `description`, or the wrong order. Task 1 adds a unit test, `test_spend_only_domains_are_childless_active_roots`, and an order test, `test_domain_order_appends_the_new_domains`. It also adds an integration test that checks the rows as written: zero children, zero links, `active`.
5. **The catalog note drifting from the data again.** The note is free text the SQL agent filters by. Task 2 adds `test_catalog_domain_note_names_every_domain`, which reads `themes.json`, so a sixth domain fails the test instead of silently misleading the agent.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `seed/data/taxonomy/themes.json` | Modify | Source of truth. Appends the two domains (end of file, after line 1009), sets Health and Education `status` to `active` (lines 388, 704) and deletes "draft" from their `source` (lines 389, 705). |
| `frontend/features/taxonomy/data/themes.json` | Modify (by `cp`) | The frontend's build-time copy, byte-identical to the seed file. |
| `backend/tests/test_taxonomy_seed.py` | Modify | `TAG_COUNTS` domain 5, plus tests for the new domains, the copy, the catalog note, the source wording and no draft status. |
| `backend/app/agent/tools/sql/catalog.py` | Modify (line 958 on #98) | The `tags.domain` column note lists five domains. |
| `frontend/features/taxonomy/TaxonomySections.tsx` | Modify (lines 12–36) | `DomainSection`: no status badge, and an empty domain renders only its source line. |
| `frontend/features/resources/TaxonomyArticle.tsx` | Modify (lines 9–37) | "How the taxonomy works": domain tags without status, and intro prose that covers theme-less domains. |
| `frontend/features/resources/tabs.ts` | Modify (line 19) | Section index labels are the plain domain labels. |
| `scripts/smoke.sh` | Modify | Adds a `check_lacks` helper (visible text only) and three taxonomy checks. |

No new files are committed. The frontend has no test runner, so Task 3 creates one throwaway checker, `../taxonomy-page-check.py`, **outside** the worktree. It reads the prerendered `frontend/.next/server/app/resources/taxonomy.html` (`/resources/[tab]` is static: `generateStaticParams` and `dynamicParams = false`).

Not touched, on purpose:
- `frontend/features/taxonomy/types.ts`: `status` stays, typed `"draft" | "active"`; no value in the data is `"draft"` any more.
- `frontend/app/taxonomy/page.tsx`: its `?domain=` regex `/^[a-z]+$/` already accepts `environment` and `others`.
- `seed/taxonomy_seed.py`: its loops handle `themes: []` already.
- `db/migrations/`: the `0002` check `kind NOT IN ('domain','cell') OR domain IS NOT NULL` is satisfied.

---

### Task 0: Worktree and toolchain

**Files:** none committed.

**Interfaces:**
- Consumes: `origin/feat/taxonomy-tags`.
- Produces:
  - `$WT`, a worktree on branch `feat/taxonomy-domains`;
  - a host venv at `$WT/backend/.venv` with pytest;
  - `$WT/frontend/node_modules`.

The compose containers mount the main checkout, which is on `master` and has neither `seed/data/taxonomy/` nor #98's seed. Every command in this plan therefore runs from the worktree on the host:
- Python: the host venv;
- Node: host Node v22.

`next build` succeeds on the host. This was verified on a copy of `origin/feat/taxonomy-tags`.

- [ ] **Step 1: Create the worktree off #98's branch**

```bash
git -C /Users/vinod/GitHub/sangam fetch origin feat/taxonomy-tags
git -C /Users/vinod/GitHub/sangam worktree add -b feat/taxonomy-domains /Users/vinod/GitHub/sangam-taxonomy-domains origin/feat/taxonomy-tags
export WT=/Users/vinod/GitHub/sangam-taxonomy-domains
```

Expected: `Preparing worktree (new branch 'feat/taxonomy-domains')`.

- [ ] **Step 2: Backend venv (Python 3.12, matching ruff's `target-version = py312`)**

```bash
cd "$WT/backend" && /opt/homebrew/bin/python3.12 -m venv .venv && .venv/bin/pip install -q -e . "pytest>=8.3" "pytest-asyncio>=0.24" "httpx>=0.27" "ruff>=0.6"
cd "$WT/backend" && .venv/bin/python -m pytest tests/test_taxonomy_seed.py -m "not integration" -q
```

The packages after `-e .` are the `[dependency-groups] dev` list in `backend/pyproject.toml`. Expected: `6 passed, 2 deselected`, which is #98's baseline for this file.

- [ ] **Step 2b: Record the whole-suite baseline on untouched #98**

```bash
cd "$WT/backend" && .venv/bin/python -m pytest -m "not integration" -q 2>&1 | tail -3; .venv/bin/ruff check . | tail -1
```

Expected: a pass/fail line and ruff's last line. Write both down. Task 5 Step 3 compares against them, so a failure already present on #98 is not taken for one this PR caused. `[tool.ruff]` sets no `select`, so ruff runs its defaults (E4, E7, E9, F). Line length (E501) is not checked, which is why #98's 150-character catalog lines pass.

- [ ] **Step 3: Frontend deps and a baseline build**

```bash
cd "$WT/frontend" && npm ci --no-audit --no-fund && npx tsc --noEmit && npm run build
```

Expected: the build lists `● /resources/taxonomy` under `/resources/[tab]`, and `ls .next/server/app/resources/taxonomy.html` exists.

---

### Task 1: Environment and Others in the taxonomy data

**Files:**
- Modify `seed/data/taxonomy/themes.json`: the end of the file, lines 1009–1011 (`    }\n  ]\n}\n`).
- Modify `frontend/features/taxonomy/data/themes.json`: replaced by `cp`.
- Modify `backend/tests/test_taxonomy_seed.py`:
  - line 18 (`TAG_COUNTS`);
  - a constants block after line 18;
  - new methods in `TestTaxonomyRows` (after line 59) and in `TestSeedAgainstPostgres` (after line 103).

**Interfaces:**
- Consumes:
  - `taxonomy_rows(themes, common) -> tuple[list[Tag], list[Link]]`;
  - `Tag(slug, label, kind, code, sort_order, parent, domain, description, status)`;
  - `seed_schedule_vii(cur)` and `seed_taxonomy(cur)`;
  - `TAXONOMY`, which is `seed/data/taxonomy`.
- Produces:
  - the tags `domain-environment` and `domain-others`;
  - the test constants `REPO`, `FRONTEND_COPY` and `SPEND_ONLY`, used by Tasks 2 and 4.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_taxonomy_seed.py`, replace line 18:

```python
TAG_COUNTS = {"sdg": 17, "population": 10, "scheme": 54, "lens": 4, "domain": 3, "theme": 11, "sub_theme": 48}
```

with:

```python
TAG_COUNTS = {"sdg": 17, "population": 10, "scheme": 54, "lens": 4, "domain": 5, "theme": 11, "sub_theme": 48}

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND_COPY = REPO / "frontend" / "features" / "taxonomy" / "data"
# Domains that classify spend fitting no programme theme. They carry no themes (spec D6).
SPEND_ONLY = ("environment", "others")
```

Append these methods to `class TestTaxonomyRows`, after `test_unknown_sdg_raises`:

```python
    def test_spend_only_domains_are_childless_active_roots(self):
        themes, common = load()
        tags, links = taxonomy_rows(themes, common)
        by_slug = {t.slug: t for t in tags}
        sources = {d["domain"]: d["source"] for d in themes["domains"]}
        for code in SPEND_ONLY:
            tag = by_slug[f"domain-{code}"]
            assert (tag.kind, tag.parent, tag.domain, tag.status) == ("domain", None, code, "active")
            assert tag.description == sources[code]
            assert not any(t.parent == tag.slug for t in tags), f"{tag.slug} has children"
            assert not any(link.tag == tag.slug for link in links), f"{tag.slug} has links"

    def test_domain_order_appends_the_new_domains(self):
        tags, _ = taxonomy_rows(*load())
        domains = [(t.code, t.sort_order) for t in tags if t.kind == "domain"]
        assert domains == [
            ("livelihoods", 0), ("health", 1), ("education", 2), ("environment", 3), ("others", 4),
        ]

    @pytest.mark.parametrize("name", ["themes.json", "common.json"])
    def test_frontend_copy_matches_seed_file(self, name):
        copy = FRONTEND_COPY / name
        if not copy.exists():
            pytest.skip(f"{copy} not in this checkout")
        assert copy.read_bytes() == (TAXONOMY / name).read_bytes(), (
            f"run: cp seed/data/taxonomy/{name} frontend/features/taxonomy/data/"
        )
```

Append this method to `class TestSeedAgainstPostgres`, after `test_a_dropped_tag_is_deprecated_not_deleted`:

```python
    def test_spend_only_domains_land_without_children_or_links(self, cur):
        seed_schedule_vii(cur)
        seed_taxonomy(cur)
        cur.execute(
            """
            SELECT t.slug, t.status, t.domain,
                   (SELECT count(*) FROM tags c WHERE c.parent_id = t.id),
                   (SELECT count(*) FROM tag_links l WHERE l.tag_id = t.id)
            FROM tags t WHERE t.slug = ANY(%s) ORDER BY t.slug
            """,
            ([f"domain-{code}" for code in SPEND_ONLY],),
        )
        assert cur.fetchall() == [
            ("domain-environment", "active", "environment", 0, 0),
            ("domain-others", "active", "others", 0, 0),
        ]
```

- [ ] **Step 2: Run the tests and watch them fail**

```bash
cd "$WT/backend" && .venv/bin/python -m pytest tests/test_taxonomy_seed.py -m "not integration" -q
```

Expected: 3 failed and 7 passed.
- `test_counts`: the Counter differs at `'domain': 3` against 5.
- `test_spend_only_domains_are_childless_active_roots`: `KeyError: 'domain-environment'`.
- `test_domain_order_appends_the_new_domains`: the list has 3 items, not 5.

- [ ] **Step 3: Append the two domains to the seed file (text insertion, no JSON round-trip)**

```bash
cd "$WT" && python3 - <<'EOF'
import pathlib
p = pathlib.Path("seed/data/taxonomy/themes.json")
s = p.read_text(encoding="utf-8")
tail = "    }\n  ]\n}\n"
assert s.endswith(tail), "themes.json no longer ends with the education domain"
new = """    },
    {
      "domain": "environment",
      "label": "Environment",
      "status": "active",
      "source": "Spend on environmental sustainability, conservation and animal welfare that is not a livelihood programme",
      "themes": []
    },
    {
      "domain": "others",
      "label": "Others",
      "status": "active",
      "source": "Spend that fits no programme domain: disaster relief, sports, central funds, administration, unlabelled or multi-sector lines",
      "themes": []
    }
  ]
}
"""
p.write_text(s[: -len(tail)] + new, encoding="utf-8")
EOF
python3 -m json.tool seed/data/taxonomy/themes.json >/dev/null && git diff --numstat seed/data/taxonomy/themes.json
```

Expected: `14	0	seed/data/taxonomy/themes.json`. Git pairs education's old closing `    }` with the new `others` closing brace, so the diff is 14 pure insertions. This was verified against #98's file. Any other count means the file was reformatted: run `git checkout -- seed/data/taxonomy/themes.json` and redo the step.

- [ ] **Step 4: Run again. Only the copy test should fail.**

```bash
cd "$WT/backend" && .venv/bin/python -m pytest tests/test_taxonomy_seed.py -m "not integration" -q
```

Expected: 1 failed (`test_frontend_copy_matches_seed_file[themes.json]` with `run: cp seed/data/taxonomy/themes.json …`) and 9 passed.

- [ ] **Step 5: Copy to the frontend and go green**

```bash
cd "$WT" && cp seed/data/taxonomy/themes.json frontend/features/taxonomy/data/themes.json
cd "$WT/backend" && .venv/bin/python -m pytest tests/test_taxonomy_seed.py -m "not integration" -q
```

Expected: `10 passed, 3 deselected`.

- [ ] **Step 6: Integration tests (only if the dev DB has `tag_links`)**

```bash
cd "$WT/backend" && TEST_DATABASE_URL=postgresql://sangam:sangam@localhost:5433/sangam .venv/bin/python -m pytest tests/test_taxonomy_seed.py -m integration -q -rs
```

Expected: one of two outcomes.
- `3 passed`. The tests roll back, so nothing persists.
- `3 skipped` with "tag_links missing: run make migrate". The shared dev DB is on `master`, which does not have #98's `0030_tag_links`. Do **not** migrate the shared dev DB to get past this. That is the user's call, and Task 5 Step 4 covers it. Record the skip in the PR.

- [ ] **Step 7: Lint and commit**

```bash
cd "$WT/backend" && .venv/bin/ruff check tests/test_taxonomy_seed.py
cd "$WT" && git add seed/data/taxonomy/themes.json frontend/features/taxonomy/data/themes.json backend/tests/test_taxonomy_seed.py
git -C "$WT" commit -F - <<'EOF'
feat(taxonomy): Environment and Others domains, with no themes

Every CSR spend line needs a domain, including spend that fits no programme
theme (spec D6). Both are appended after Education, so sort_order 3 and 4,
and carry no themes, sub-themes or links. Tag counts: 5 domains, the rest
unchanged. A test now fails when the frontend copy drifts from the seed file.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

**Deliverable:**
- `taxonomy_rows` yields five domains, the two new ones childless and active;
- the frontend copy is byte-identical;
- `pytest tests/test_taxonomy_seed.py -m "not integration"` is green.

---

### Task 2: The catalog's `tags.domain` note names five domains

**Files:**
- Modify `backend/app/agent/tools/sql/catalog.py`, line 958 on #98, inside `Table(name="tags", …)`.
- Modify `backend/tests/test_taxonomy_seed.py`, adding a module-level test at the end.

**Interfaces:**
- Consumes:
  - `app.agent.tools.sql.catalog.COLUMNS: Mapping[str, Mapping[str, Column]]`;
  - `Column.note`;
  - `load()` from Task 1's test module.
- Produces: the note text `"'livelihoods' | 'health' | 'education' | 'environment' | 'others'; required for kind 'domain' and 'cell'"`.

- [ ] **Step 1: Write the failing test**

Append to the end of `backend/tests/test_taxonomy_seed.py`:

```python
def test_catalog_domain_note_names_every_domain():
    """The SQL agent filters tags.domain by this note; it must list every domain the seed writes."""
    from app.agent.tools.sql import catalog as cat

    note = cat.COLUMNS["tags"]["domain"].note
    themes, _ = load()
    missing = [d["domain"] for d in themes["domains"] if f"'{d['domain']}'" not in note]
    assert not missing, f"tags.domain note lacks {missing}: {note!r}"
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd "$WT/backend" && .venv/bin/python -m pytest tests/test_taxonomy_seed.py::test_catalog_domain_note_names_every_domain -q
```

Expected: FAILED with `tags.domain note lacks ['environment', 'others']`.

- [ ] **Step 3: Update the note**

In `backend/app/agent/tools/sql/catalog.py`, replace:

```python
            Column("domain", "text", note="'livelihoods' | 'health' | 'education'; required for kind 'domain' and 'cell'"),
```

with:

```python
            Column("domain", "text", note="'livelihoods' | 'health' | 'education' | 'environment' | 'others'; required for kind 'domain' and 'cell'"),
```

- [ ] **Step 4: Run the test and the catalog suite**

```bash
cd "$WT/backend" && .venv/bin/python -m pytest tests/test_taxonomy_seed.py tests/test_sql_catalog.py -m "not integration" -q && .venv/bin/ruff check app/agent/tools/sql/catalog.py tests/test_taxonomy_seed.py
```

Expected: all pass, and ruff prints `All checks passed!`. The new note line is about 150 characters, but E501 is not selected.

- [ ] **Step 5: Commit**

```bash
cd "$WT" && git add backend/app/agent/tools/sql/catalog.py backend/tests/test_taxonomy_seed.py
git -C "$WT" commit -F - <<'EOF'
feat(catalog): tags.domain lists Environment and Others

The SQL agent reads this note to filter domain tags. A test now reads
themes.json, so the next domain added fails it instead of going unlisted.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

**Deliverable:** `cat.COLUMNS["tags"]["domain"].note` names all five domains, and a test guards it.

---

### Task 3: `/resources/taxonomy` renders all five domains

**Files:**
- Modify `frontend/features/taxonomy/TaxonomySections.tsx`, lines 12–36 (`DomainSection`).
- Modify `frontend/features/resources/TaxonomyArticle.tsx`, lines 10–14 (the intro paragraph).
- Create the throwaway, uncommitted `/Users/vinod/GitHub/taxonomy-page-check.py`, next to the worktree.

**Interfaces:**
- Consumes:
  - `DOMAINS: Domain[]` from `@/features/taxonomy/data`, which now has five entries;
  - `Domain.themes: Theme[]`, which may be empty.
- Produces:
  - `<section id="environment">` and `<section id="others">`, each holding only a heading and `<p>{source}.</p>`;
  - index links `href="#environment"` and `href="#others"`. These already come from `TAXONOMY_SECTIONS`, which maps `DOMAINS`.

- [ ] **Step 1: Write the failing check**

Create `/Users/vinod/GitHub/taxonomy-page-check.py`:

```python
"""Checks the prerendered /resources/taxonomy page. Not committed: the frontend has no test runner.

Usage, from the worktree root after `npm run build`:  python3 ../taxonomy-page-check.py render|draft|all
"""
import html
import pathlib
import re
import sys

PAGE = pathlib.Path("frontend/.next/server/app/resources/taxonomy.html")
raw = PAGE.read_text(encoding="utf-8")
# Visible text only: the RSC payload in <script> carries raw data (a client component receives the
# whole domain object) that a reader never sees, so it must not count.
body = re.sub(r"<(script|style)\b.*?</\1>", " ", raw, flags=re.S | re.I)
text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<!--.*?-->", "", body, flags=re.S))).split())

SPEND_ONLY = {
    "environment": "Spend on environmental sustainability, conservation and animal welfare that is not a livelihood programme.",
    "others": "Spend that fits no programme domain: disaster relief, sports, central funds, administration, unlabelled or multi-sector lines.",
}
part = sys.argv[1] if len(sys.argv) > 1 else "all"
failures: list[str] = []

if part in ("render", "all"):
    for code in ("livelihoods", "health", "education", *SPEND_ONLY):
        if f'<section id="{code}"' not in body:
            failures.append(f"no section anchored #{code}")
        if f'href="#{code}"' not in body:
            failures.append(f"section index has no link to #{code}")
    for code, source in SPEND_ONLY.items():
        if source not in text:
            failures.append(f"#{code} does not show its source line")
        section = re.search(rf'<section id="{code}".*?</section>', body, re.S)
        if section and 'class="card"' in section.group(0):
            failures.append(f"#{code} renders a theme card")
    if re.search(r"\b0 themes\b", text):
        failures.append("an empty domain prints '0 themes'")

if part in ("draft", "all"):
    hits = [m.group(0) for m in re.finditer(r".{0,25}\bdrafts?\b.{0,25}", text, re.I)]
    if hits:
        failures.append(f"visible 'draft' text: {hits}")

print("\n".join(failures) or f"taxonomy page check ({part}): ok")
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Build and run it to watch it fail**

```bash
cd "$WT/frontend" && npm run build >/dev/null && cd "$WT" && python3 ../taxonomy-page-check.py render
```

Expected: exit 1 with `an empty domain prints '0 themes'`. Task 1's data already gives both sections, their links and their source lines, so this is the only failure.

- [ ] **Step 3: Branch `DomainSection` on an empty theme list**

In `frontend/features/taxonomy/TaxonomySections.tsx`, replace lines 21–33:

```tsx
      <p className="muted measure m-0">
        {domain.themes.length} themes, {subThemes} sub-themes. {domain.source}.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {domain.themes.map((theme) => (
          <ThemeCard
            key={theme.code}
            theme={theme}
            open={open[theme.code] ?? false}
            onToggle={() => setOpen({ ...open, [theme.code]: !open[theme.code] })}
          />
        ))}
      </div>
```

with:

```tsx
      {/* Environment and Others have no themes: they show only what spend they hold. */}
      <p className="muted measure m-0">
        {domain.themes.length > 0 && `${domain.themes.length} themes, ${subThemes} sub-themes. `}
        {domain.source}.
      </p>
      {domain.themes.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {domain.themes.map((theme) => (
            <ThemeCard
              key={theme.code}
              theme={theme}
              open={open[theme.code] ?? false}
              onToggle={() => setOpen({ ...open, [theme.code]: !open[theme.code] })}
            />
          ))}
        </div>
      )}
```

- [ ] **Step 4: Make the intro prose true for theme-less domains**

In `frontend/features/resources/TaxonomyArticle.tsx`, replace lines 10–14:

```tsx
        <p className="measure m-0">
          Work is classified by what it does, in the terms funders plan with: each domain has a few
          themes, and each theme a handful of sub-themes. A programme, organisation, funder or call is
          tagged with one or more sub-themes, and everything else follows from them.
        </p>
```

with:

```tsx
        <p className="measure m-0">
          Work is classified by what it does, in the terms funders plan with: each programme domain has
          a few themes, and each theme a handful of sub-themes. A programme, organisation, funder or call
          is tagged with one or more sub-themes, and everything else follows from them. Environment and
          Others have no themes: they give a domain to CSR spend that fits no programme.
        </p>
```

- [ ] **Step 5: Type-check, lint, build, and run the check to green**

```bash
cd "$WT/frontend" && npx tsc --noEmit && npm run lint && npm run build >/dev/null && cd "$WT" && python3 ../taxonomy-page-check.py render
```

Expected: tsc and lint are clean, and the check prints `taxonomy page check (render): ok`.

- [ ] **Step 6: Commit**

```bash
cd "$WT" && git add frontend/features/taxonomy/TaxonomySections.tsx frontend/features/resources/TaxonomyArticle.tsx
git -C "$WT" commit -F - <<'EOF'
feat(taxonomy-page): Environment and Others render as source-only domains

A domain with no themes shows its one-line source and no theme cards,
instead of "0 themes, 0 sub-themes" over an empty list. The section index
already maps every domain, so it lists all five.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

**Deliverable:** the built `/resources/taxonomy` has five anchored domain sections and five index links. Environment and Others show only their source line.

---

### Task 4: No "Draft" on the taxonomy page

**Files:**
- Modify `seed/data/taxonomy/themes.json`: lines 388–389 (Health `status` and `source`) and lines 704–705 (Education `status` and `source`). Then `cp` it to `frontend/features/taxonomy/data/themes.json`.
- Modify `backend/tests/test_taxonomy_seed.py`, adding two methods to `TestTaxonomyRows`.
- Modify `frontend/features/taxonomy/TaxonomySections.tsx`, lines 17–20 (the heading row with the status badge).
- Modify `frontend/features/resources/TaxonomyArticle.tsx`, lines 31–37 (the domain tag row).
- Modify `frontend/features/resources/tabs.ts`, line 19.

**Interfaces:**
- Consumes:
  - `Domain.status`, still in the data and the type, `"active"` on every domain, now read by no component;
  - `Tag` from `@/components/ui`, still used in both `.tsx` files.
- Produces: page text with no `\bdrafts?\b`, and no domain with `status` `"draft"`. The Health source becomes "Drawn from the Health programme areas, regrouped in funder-facing themes", and Education's becomes the same with "Education".

- [ ] **Step 1: Write the failing backend test (the data half)**

Append to `class TestTaxonomyRows` in `backend/tests/test_taxonomy_seed.py`:

```python
    def test_no_domain_source_says_draft(self):
        """`source` renders on /resources/taxonomy and becomes tags.description, so it never says draft."""
        themes, _ = load()
        drafty = {d["domain"]: d["source"] for d in themes["domains"] if "draft" in d["source"].lower()}
        assert not drafty, drafty

    def test_no_domain_is_draft(self):
        """No domain is draft any more: every status is active, in the file and so in tags.status."""
        themes, common = load()
        assert {d["domain"]: d["status"] for d in themes["domains"] if d["status"] != "active"} == {}
        tags, _ = taxonomy_rows(themes, common)
        assert {t.slug: t.status for t in tags if t.kind == "domain" and t.status != "active"} == {}
```

- [ ] **Step 2: Run both checks and watch them fail**

```bash
cd "$WT/backend" && .venv/bin/python -m pytest tests/test_taxonomy_seed.py -k "no_domain_source_says_draft or no_domain_is_draft" -q
cd "$WT" && python3 ../taxonomy-page-check.py draft
```

Expected:
- pytest: 2 failed. `test_no_domain_source_says_draft` lists `health` and `education` with "…programme-areas draft…"; `test_no_domain_is_draft` lists `{'health': 'draft', 'education': 'draft'}`;
- the page check exits 1. It lists `Health (draft)` and `Education (draft)` (the index), `Health · Draft` and `Education · Draft` (the tag row), the two `Draft` badges, and the two "programme-areas draft" source lines.

- [ ] **Step 3: Make Health and Education active, delete "draft" from their `source`, and re-copy**

```bash
cd "$WT" && python3 - <<'EOF'
import pathlib
p = pathlib.Path("seed/data/taxonomy/themes.json")
s = p.read_text(encoding="utf-8")
assert s.count("programme-areas draft, regrouped") == 2
assert s.count('"status": "draft",') == 2
s = s.replace("programme-areas draft, regrouped", "programme areas, regrouped")
s = s.replace('"status": "draft",', '"status": "active",')
p.write_text(s, encoding="utf-8")
EOF
cp seed/data/taxonomy/themes.json frontend/features/taxonomy/data/themes.json
git diff --numstat HEAD -- seed/data/taxonomy/themes.json; grep -c '"status": "draft"' seed/data/taxonomy/themes.json
```

Expected: `4	4	seed/data/taxonomy/themes.json` (two `status` lines and two `source` lines), then `0`. Text replacement, not a `json.dump` round-trip, so nothing else in the file is re-escaped.

- [ ] **Step 4: Remove the status badge from domain headings**

In `frontend/features/taxonomy/TaxonomySections.tsx`, replace lines 17–20:

```tsx
      <div className="flex flex-wrap items-center gap-2.5">
        <h3 style={{ fontSize: "var(--fs-lg)" }}>{domain.label}</h3>
        {domain.status === "draft" ? <Tag tone="accent">Draft</Tag> : <Tag tone="accent-2">Active</Tag>}
      </div>
```

with:

```tsx
      <h3 style={{ fontSize: "var(--fs-lg)" }}>{domain.label}</h3>
```

(`Tag` stays imported: `SubThemeRow` and `SharedSection` use it.)

- [ ] **Step 5: Remove the status from the "How the taxonomy works" tags**

In `frontend/features/resources/TaxonomyArticle.tsx`, replace lines 31–37:

```tsx
        <div className="flex flex-wrap gap-2">
          {DOMAINS.map((d) => (
            <Tag key={d.domain} tone={d.status === "draft" ? "accent" : "accent-2"}>
              {d.label} · {d.status === "draft" ? "Draft" : "Active"}
            </Tag>
          ))}
        </div>
```

with:

```tsx
        <div className="flex flex-wrap gap-2">
          {DOMAINS.map((d) => (
            <Tag key={d.domain} tone="accent-2">{d.label}</Tag>
          ))}
        </div>
```

- [ ] **Step 6: Plain labels in the section index**

In `frontend/features/resources/tabs.ts`, replace line 19:

```ts
  ...DOMAINS.map((d) => ({ id: d.domain, label: d.status === "draft" ? `${d.label} (draft)` : d.label })),
```

with:

```ts
  ...DOMAINS.map((d) => ({ id: d.domain, label: d.label })),
```

- [ ] **Step 7: Run everything to green**

```bash
cd "$WT/backend" && .venv/bin/python -m pytest tests/test_taxonomy_seed.py -m "not integration" -q
cd "$WT/frontend" && npx tsc --noEmit && npm run lint && npm run build >/dev/null && cd "$WT" && python3 ../taxonomy-page-check.py all
cd "$WT" && git grep -n 'status === "draft"\|"Draft"\|(draft)' -- frontend/features/taxonomy frontend/features/resources
```

Expected:
- pytest: `13 passed, 3 deselected`. That is 11 from Tasks 1–2 plus these two; the copy test stays green because Step 3 re-copied.
- `npx tsc --noEmit` is clean with `Domain.status` still typed `"draft" | "active"`: no component reads it now, and the data holds only `"active"`.
- The page check prints `taxonomy page check (all): ok`.
- `git grep` prints nothing and exits 1.

- [ ] **Step 8: Commit**

```bash
cd "$WT" && git add seed/data/taxonomy/themes.json frontend/features/taxonomy/data/themes.json backend/tests/test_taxonomy_seed.py frontend/features/taxonomy/TaxonomySections.tsx frontend/features/resources/TaxonomyArticle.tsx frontend/features/resources/tabs.ts
git -C "$WT" commit -F - <<'EOF'
feat(taxonomy-page): no domain is draft, and no Draft labels

Removes the Draft/Active badge on domain headings, the status in the "How
the taxonomy works" tags and the "(draft)" index labels (spec D10). Health
and Education become active, and the word "draft" is deleted from their
source lines, which render verbatim. The status field stays in themes.json,
tags.status and the frontend type.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

**Deliverable:**
- the built page has no visible "draft";
- every domain's `status` is `active`, and the field stays in the data;
- backend tests stop a `source` from reintroducing the word and a domain from going back to draft.

---

### Task 5: Smoke checks, re-seed, PR

**Files:** Modify `scripts/smoke.sh`:
- add a `check_lacks` helper after `check_json` (ends at line 53 on #98);
- add three lines after the `check_contains "taxonomy shows the SHG theme"` line (line 76 on #98).

**Interfaces:**
- Consumes the smoke helpers `ok`, `bad` and `AUTH`, and the `$FRONTEND` URL.
- Produces `check_lacks name url regex [max-time]`. It fails when the page's visible text (scripts, styles, comments and tags stripped) matches `regex` case-insensitively, or when the page cannot be read.

- [ ] **Step 1: Add the helper and the checks**

In `scripts/smoke.sh`, insert after the closing `}` of `check_json`:

```bash

check_lacks() { # name url regex [max-time] — fails when the page's VISIBLE text matches (case-insensitive)
  local name="$1" url="$2" pattern="$3" t="${4:-90}"
  local hits
  # Scripts are stripped first: the RSC payload carries raw data that is never shown.
  if ! hits=$(curl -sf --max-time "$t" "${AUTH[@]}" "$url" | PATTERN="$pattern" python3 -c '
import html, os, re, sys
page = sys.stdin.read()
if not page:
    sys.exit("empty response")
page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S | re.I)
page = re.sub(r"<!--.*?-->", "", page, flags=re.S)
text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())
print("; ".join(m.group(0) for m in re.finditer(r".{0,20}(?:" + os.environ["PATTERN"] + r").{0,20}", text, re.I)))
' 2>&1); then
    bad "$name — could not read $url: $hits"
  elif [[ -n "$hits" ]]; then
    bad "$name — visible text on $url matches: $hits"
  else
    ok "$name"
  fi
}
```

Then, directly after `check_contains "taxonomy shows the SHG theme" "$FRONTEND/resources/taxonomy" "Economic empowerment of SHGs" 90`, add:

```bash
check_contains "taxonomy shows Environment" "$FRONTEND/resources/taxonomy" "conservation and animal welfare" 90
check_contains "taxonomy shows Others"      "$FRONTEND/resources/taxonomy" "fits no programme domain" 90
check_lacks    "taxonomy shows no Draft"    "$FRONTEND/resources/taxonomy" '\bdrafts?\b'
```

- [ ] **Step 2: Prove the helper fails against today's site, then passes against the branch build**

`localhost:3000` serves `master`, so it shows the failing state:

```bash
cd "$WT" && SMOKE_SKIP_LLM=1 bash scripts/smoke.sh 2>&1 | grep -E "taxonomy shows (Environment|Others|no Draft)"
```

Expected: three `✗` lines:
- `taxonomy shows Environment — response … does not contain …`;
- the same for Others;
- `taxonomy shows no Draft — visible text … matches: … Health (draft) …`.

Then serve the branch build on a spare port and point the smoke script at it:

```bash
cd "$WT/frontend" && (npx next start -p 3100 >/dev/null 2>&1 &) && for i in $(seq 60); do curl -sf -o /dev/null http://localhost:3100/resources/taxonomy && break; sleep 1; done
cd "$WT" && FRONTEND_URL=http://localhost:3100 SMOKE_SKIP_LLM=1 bash scripts/smoke.sh 2>&1 | grep -E "taxonomy"
pkill -f "next start -p 3100"
```

Expected:
- `✓ taxonomy copies match their seed files`;
- `✓ taxonomy shows the SHG theme`;
- `✓ taxonomy shows Environment`;
- `✓ taxonomy shows Others`;
- `✓ taxonomy shows no Draft`.

Registry checks on `:3100` may fail if `next start` lacks the backend env. Only the taxonomy lines matter here.

- [ ] **Step 3: Full backend unit suite and lint**

```bash
cd "$WT/backend" && .venv/bin/python -m pytest -m "not integration" -q && .venv/bin/ruff check .
```

Expected: the same result as the Task 0 Step 2b baseline, plus the six tests this PR adds (2 + 2 parametrised in Task 1, 1 in Task 2, 1 in Task 4), and no new failures. Ruff's last line also matches the baseline.

- [ ] **Step 4: Re-seed (needs the user's OK, because it writes to the shared dev DB)**

The spec's `make taxonomy-seed` runs in the compose `backend` container, which mounts the main checkout (`master`), so it would load master's data. Run the worktree's seed from the host instead, and only if `0030_tag_links` is applied:

```bash
docker compose -f /Users/vinod/GitHub/sangam/docker-compose.yml exec -T postgres psql -U sangam -d sangam -tAc "SELECT to_regclass('tag_links')"
```

- If that prints `tag_links`, run:

  ```bash
  cd "$WT" && DATABASE_URL=postgresql://sangam:sangam@localhost:5433/sangam backend/.venv/bin/python -m seed.taxonomy_seed
  ```

  Expected: `seeded: 12 Schedule VII categories as tags(kind='csr_sector')`, then `seeded: 17 sdg, 10 population, 54 scheme, 4 lens, 5 domain, 11 theme, 48 sub_theme, 211 links`. The writes are idempotent upserts and change two rows: `domain-environment` and `domain-others` are added, and the Health and Education `description` is reworded.
- If it prints an empty line, skip the step and say in the PR that the re-seed waits for #98's migration on the dev DB. The unit tests and the rolled-back integration test cover the seed.

- [ ] **Step 5: Commit**

```bash
cd "$WT" && git add scripts/smoke.sh
git -C "$WT" commit -F - <<'EOF'
test(smoke): taxonomy shows Environment and Others and no Draft

check_lacks matches visible text only. The RSC payload keeps the raw
data, which is never shown, so a plain grep would test the wrong thing.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git -C "$WT" log --oneline origin/feat/taxonomy-tags..HEAD
```

Expected: five commits:
- `feat(taxonomy)`;
- `feat(catalog)`;
- two `feat(taxonomy-page)`;
- `test(smoke)`.

- [ ] **Step 6: Hand off. Do not push.**

Finish with superpowers:finishing-a-development-branch. Pushing and opening the PR are the user's call.

The PR stacks on #98:
- base `feat/taxonomy-tags`;
- head `feat/taxonomy-domains`.

It needs a retarget to `master` once #98 merges. Put three things in the PR description:
- Step 4's outcome: re-seeded, or waiting for `0030` on the dev DB;
- that Health and Education are now `active` and the word "draft" was deleted from their `source` strings, so a re-seed updates `tags.status` and `tags.description` for both;
- that the `localhost:3000` smoke checks go green only once that server runs this branch.

**Deliverable:** five commits on `feat/taxonomy-domains`, ready to push, where:
- `pytest -m "not integration"` and `ruff` match the baseline, plus the new passing tests;
- `tsc`, `lint` and `next build` are clean;
- smoke against the branch build (`:3100`) passes every taxonomy check.

---

## Self-review: spec §1 coverage

| §1 requirement | Task |
|---|---|
| Add Environment and Others (exact JSON, `themes: []`) to `seed/data/taxonomy/themes.json` | Task 1 Step 3 |
| `make taxonomy-seed` writes `domain-environment` and `domain-others`, kind `domain`, no links | Task 1 tests (unit and integration); Task 5 Step 4 re-seed |
| Copy the file to `frontend/features/taxonomy/data/` (smoke diffs the two) | Task 1 Step 5, Task 4 Step 3; byte-equality test in Task 1 |
| `catalog.py`: `tags.domain` note lists five domains | Task 2 |
| `test_taxonomy_seed.py`: `TAG_COUNTS["domain"]` becomes 5 | Task 1 Step 1 |
| `/resources/taxonomy` renders all five; Environment and Others show `source`, no theme cards | Task 3 (built-HTML check `render`); Task 5 smoke |
| Section index lists all five | Task 3 check (`href="#<code>"` ×5); Task 4 Step 6 plain labels |
| Remove the status badges on domain headings | Task 4 Step 4 |
| Remove the status tags in "How the taxonomy works" | Task 4 Step 5 |
| Remove "Health and Education are drafts" wording: the `(draft)` index labels and the word "draft" in their source text | Task 4 Steps 3 and 6 |
| No domain is draft: Health and Education `status` becomes `active` | Task 4 Step 3 (`grep -c '"status": "draft"'` = 0); `test_no_domain_is_draft` |
| The `status` field stays in the data and `tags.status` (D10) | Task 4 Step 3; `types.ts` untouched (`"draft"` or `"active"` kept, so `tsc` stays green) |

Decisions (from the user): draft is removed from the taxonomy, not reworded. Health and Education become `active`, and their `source` strings lose only the word "draft" ("programme-areas draft, regrouped" becomes "programme areas, regrouped"). Both changes reach `tags` on re-seed. The frontend type keeps `"draft" | "active"`; narrowing it to `"active"` would also compile, but keeping it touches nothing. The file's `_help` note ("Crosswalks are a draft for review") is not a domain `source`, is not rendered on the page, and is left alone.
