# Import tagging: implementation plan and smoke test

The spec is `2026-10-11-import-tagging.md`; this is how it was built, what was tested, and how to
check it live. Built in #162 (merged 2026-10-11), on top of #161 (match-v2).

## Implementation plan

| # | Step | Files | Status |
|---|---|---|---|
| 1 | A backend copy of the taxonomy, since the deployed backend has no `seed/` | `backend/app/ingest/data/{themes,common}.json`, `scripts/smoke.sh`, `frontend/features/taxonomy/data/README.md` | done |
| 2 | Load the vocabulary: each code's label and its `tags.slug` | `ingest/taxonomy.py` (`VOCABULARY`, `TAG_SLUGS`, `TAG_KINDS`) | done |
| 3 | Tag fields on the `program`, `identity` and `org_identity` findings: `themes` (at most 3), `populations`, `lenses`, `tag_note` (required with any tag). Codes are offered in the schema as `examples`; an unknown one is kept, lower-cased and de-duplicated | `ingest/research_records.py` (`Tagged`) | done |
| 4 | Declare the fields in the registry, with every code and label, so `research_goals` shows them | `ingest/expectations.py` (`_TAGS` in `EXTRA`) | done |
| 5 | Carry the fields into the records | `ingest/records.py` (`Tags` on `ProgramRecord`, `FunderRecord`, `OrgRecord`) | done |
| 6 | Write them. `write_tags` resolves each code to its unique slug and inserts it inferred, as `sangam-import`, with the note. An unknown code is dropped and noted; a code missing from `tags` (seed behind) is noted | `ingest/writer.py` | done |
| 7 | Call it after each programme, funder and org write, and count `written.tags` | `ingest/promote.py` | done |
| 8 | Log tag writes so undo removes them | `db/migrations/0043_tag_writes_logged.sql`, `ingest/undo.py` (`LOGGED`) | done; applied on staging 2026-10-11 10:56 UTC |
| 9 | Tell the researcher and the supervisor | `prompts/entity_researcher.md`; skills `ngo-credential-research`, `funder-intake-research`, `catalog-mapping`, `catalog-write-report` | done |
| 10 | Apply 0043 on staging, and merge #162 | | done |
| 11 | Deploy (Actions → Deploy → Run workflow on `master`) | | **to do** |
| 12 | The smoke test below | | B done locally (throwaway Postgres), 2026-10-11; C after deploy |
| 13 | Backfill: rerun Import on the 8 staging orgs (all have 0 tags today) | | after 12 passes |

Decisions: tags count straight away, lenses are descriptive, no profile editing yet, and an
unknown code is dropped and noted. Saved matches are not rerun automatically.

## What has been tested

**Automated** (`backend/tests/test_import_tagging.py` and the registry tests in `test_ingest.py`):

- The backend copies equal the seed files; theme and sub-theme codes never collide; every slug the
  writer resolves is one `seed.taxonomy_seed` writes.
- A finding keeps an unknown code for the writer to drop; refuses a tag with no `tag_note`; refuses
  more than three themes; the schema offers the codes.
- Model fields equal the registry's expected fields, and every field reaches a record.
- Integration, against a migrated and seeded scratch Postgres: `write_tags` writes
  `is_inferred`, `sangam-import` tags with the note, drops and notes an unknown code, and a rerun
  adds nothing.

**By hand, on a scratch database:**

- An org research row with a tagged `org_identity` and a tagged programme, through `promote()`,
  gave `written: {"tags": {"added": 6}, "programs": {"added": 1}}`, nothing held: 2 `org_tags`
  (`theme-shg-empowerment`, `lens-women_girls`) and 4 `program_tags`.
- With `sangam.promotion_id` set, an `org_tags` insert appears in `catalog_writes`, so undo sees it.
- match-v2 (#161): a sub-theme against a funder's theme scored theme 25; a clause-only funder 15.

**Full suite:** 863 passed, with the same 7 failures as master (storage, vault and model defaults
in the dev container).

**Still untested after the local smoke run:**

1. Matching against a funder that has real themes: no seeded funder has taxonomy tags or classified
   spend lines yet.
2. The deployed backend loading `app/ingest/data/*.json` (part C).

## Smoke test

Run on staging; part C after step 11. Staff sign-in is needed for Import and undo.

### A. The migration (done 2026-10-11; rerun the check after any restore)

```sql
SELECT tgrelid::regclass FROM pg_trigger
WHERE tgname = 'log_catalog_write' AND tgrelid::regclass::text IN ('org_tags', 'program_tags');
-- expect 2 rows
```

### B. Locally against staging (`make up ENV=staging`), before deploy

1. **Backend boots.** `curl -s localhost:8010/health` is OK, which proves the vocabulary files load.
2. **The researcher sees the codes.** In Import, research **KABIL** (org 4, kabilindia.org) from its
   public website only. In the Langfuse trace, the researcher's task lists `themes (text[]) — one of:
   skilling = Skilling for jobs & employment …`.
3. **Save it, then read the report.** The write report gives a tag count and relays any dropped
   code verbatim. Then:

   ```sql
   SELECT p.name, t.kind, t.slug, pt.tagged_by, pt.is_inferred, left(pt.note, 60) AS note
   FROM program_tags pt JOIN programs p ON p.id = pt.program_id JOIN tags t ON t.id = pt.tag_id
   WHERE p.org_id = 4 ORDER BY 1, 2;
   SELECT t.kind, t.slug, ot.tagged_by, left(ot.note, 60) AS note
   FROM org_tags ot JOIN tags t ON t.id = ot.tag_id WHERE ot.org_id = 4;
   ```

   **Pass if** every tag is `sangam-import`, `is_inferred`, with a note quoting the source; no
   programme has more than 3 theme tags; and the themes are plausible for what KABIL describes. Read
   the notes, not just the counts.

4. **Match.** In Ask, "Which funders can KABIL apply to?" (or `make match ORG=kabil ENV=staging`).
   **Pass if** theme is judged (not "no themes recorded for the organisation") for any funder whose
   spend lines or tags are classified, and the run's rubric is `match-v2`.
5. **Undo.** Undo the save from step 3 (`POST /api/ingest/promotions/{id}/undo`, or the Import
   screen). **Pass if** the KABIL tags from step 3 are gone (rerun the queries: 0 rows) and the
   programmes are back to how they were. Then save again for real.

### C. After deploy

1. `curl -sI <backend>/health` gives 200, with `x-vercel-id: bom1::bom1`.
2. Repeat B.2–B.3 for one more org from the deployed app (suggested: **MOSONiE**, org 7).
3. `make smoke` passes, including both "taxonomy copies … match their seed files" lines.

### If it fails

- **Bad tags:** undo the save (B.5). Nothing else is touched, since tags are insert-only and a person's tags are never written over.
- **Backend won't boot** on a missing vocabulary file: redeploy the previous build. #162 has no
  schema change the old code depends on (0043 only adds triggers).

## Smoke test results (2026-10-11, local)

Part B, run on a throwaway stack: a fresh `pgvector/pgvector:pg17` container, migrated, with
`seed.seed` and `seed.taxonomy_seed` loaded. A separate backend on :8011 pointed only at it, with
`SUPABASE_URL` and the service key empty (no auth, no storage), Langfuse and the graph off, and
`DEV_AUTH=1`. Import was driven over AG-UI as the screen does, answering the sources card with public
websites only. Staging was not touched.

| Step | Result |
|---|---|
| B.1 backend boots | pass: `/health` ok, vocabulary loaded |
| B.2 researcher tags | pass: one KABIL run, 39 findings. Six carry tags, all valid codes, none dropped, each with a quoted `tag_note`. It used new Others sub-themes (`local-governance`, `entitlements-access`). The research grader asked for one revision, about gap details, not tags |
| B.3 save writes them | pass: the save route wrote 12 `program_tags` and 5 `org_tags`, all `sangam-import`, `is_inferred`, with notes; `reasons` empty. The 4 seed Darpan tags were untouched |
| B.4 match reads them | pass: match-v2 loads KABIL as 8 themes and 4 clauses. Local funders have no themes, so theme is "no themes recorded for the funder"; one given SHG empowerment scores 25, met |
| B.5 undo removes them | pass: `catalog_writes` logged all 17 tag inserts; undo removed 41 rows and restored 10, leaving 0 Import tags and 4 seed tags |

The run cost a few dollars in model calls. Judgement call to watch: "SC/ST/Women" became
`tribal-communities`.

**Deferred (UI, not now):** the review step shows tags as raw codes ("livelihood-diversification,
nrm-water") and the `tag_note` as an unlabelled fact. Showing labels needs a mock first.

## After the smoke test

- Backfill: rerun Import on the remaining 6 staging orgs (Diya, The Action Northeast Trust, SATRA,
  Projonmo, Better Life, MANEDA), with sources ticked as for a normal run.
- Funder focus: rerun Import on SBI Foundation and Infosys Foundation to write `funder_tags` from
  their stated focus.
- Funder Match: rerun a saved match by hand where you want a fresh score. Nothing reruns on its own.
