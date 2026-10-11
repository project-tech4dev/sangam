# Import writes themes, populations and lenses

Status: built on `feat/import-tagging`, 2026-10-11; the open questions were decided the same day (end of this file). Step 2 of the bulk-load plan. It depends on match-v2
(`docs/features/2026-10-11-funder-match-v2-themes.md`), which makes Funder Match read these tags.

## Problem

Funder Match judges theme (25 points) and population (15) from tags, and Import writes almost none.
- **Orgs and programmes:** no `org_tags` or `program_tags` are written. `ProgramRecord` has no themes.
- **Funders:** only Schedule VII clauses reach `funder_tags` (`write_funder_tag`, keyword-matched from
  the filed sector). Spend and programme lines do carry `domain_tag_id` and `theme_tag_id` (D11),
  and match-v2 reads those.

So, on staging today, theme and population are "unknown" for all 7 orgs and every match is scored
on geography and eligibility alone. Bulk-loading CSOs before this lands would load them untagged.

## What gets tagged

| Side | Table | From |
|---|---|---|
| Programme | `program_tags` | the `program` finding: what the programme does and for whom |
| Org | `org_tags` | the `org_identity` finding's tags: the org's stated focus, when the source states one beyond its programmes |
| Funder | `funder_tags` | the `identity` finding's tags: the stated focus in a CSR policy or foundation page. Spend lines stay as they are |

What can be tagged, all from the closed taxonomy (`seed/data/taxonomy/`):
- **Themes:** a sub-theme code, or a theme code when only the broad area is clear. Never a domain
  alone: the domain follows from the theme.
- **Populations:** codes from `common.json` `population`.
- **Lenses:** codes from `themes.json` `lenses`. They are recorded but not scored in match-v2.

## Shape

A `Tagged` mixin (`research_records.py`) gives the same four fields to `program`, the funder's `identity`
and the org's `org_identity`. Riding on the finding that names the subject avoids a new concept: a
tag table's `tag_id` names no subject of its own, which is why `org_tags` was never a concept.
`expectations.EXTRA` declares the fields, so `research_goals` lists them for the researcher:

```python
themes: list[str] = []              # theme and sub-theme codes, offered in the schema; at most three
populations: list[str] = []
lenses: list[str] = []
tag_note: str | None                # required when any list is non-empty: the words it rests on
```

- **The researcher reads the codes with their labels.** `research_goals` lists each one, e.g.
  `fln = Foundational literacy & numeracy (under early-foundational)`, from the same copies.
- **The vocabulary is a hint in the schema, not a check.** The codes reach the schema as `examples`,
  built when the module is imported from
  `backend/app/ingest/data/{themes,common}.json`, copies of `seed/data/taxonomy/` (the deployed
  backend has no `seed/`; `make smoke` and `test_import_tagging.py` fail while they differ), so the researcher's schema offers the allowed codes. That
  avoids a second copy in a prompt (prompt substitution is reserved for `MAX_PARALLEL_RESEARCH`), and
  an invented code is kept on the finding and dropped, with a note, when it is written (decision 4).
- **At most three themes per programme or focus.** That forces a primary reading over a scatter of
  tags.
- **`tag_note` is required,** like a spend line's `classification_note`. A tag is an inference, and
  it names its evidence, for example "programme page: 'women's SHG federations in Udalguri'".

## Writing

- `writer.write_tags(conn, column, subject_id, record)` resolves each code to its `tags.slug`
  (`taxonomy.TAG_SLUGS`, the seed's `<kind>-<code>`), so the lookup rests on the unique slug, and skips a
  deprecated tag. The finding stores codes, not `tags.id`: ids differ between databases, and research is
  saved in one and may be promoted in another; `promote.py` calls it after each programme, funder and org write.
  - A code outside the taxonomy is dropped and noted in `report["reasons"]`; one in the taxonomy but not in
    `tags` means the seed is behind, and is noted the same way.
  - They write `role='primary'`, `is_inferred=true`, `tagged_by='import'` and the note.
- **Additive, like everything Import writes.** A re-import adds tags and never removes one a person
  set (`tagged_by <> 'import'`).
- **Plan mode** skips the write, as `write_funder_tag` does.
- **Logged in `catalog_writes`,** so staff can undo the save: `0043_tag_writes_logged` adds the trigger
  to `org_tags` and `program_tags` (`funder_tags` already had it), and `undo.LOGGED` names them.
- **`catalog-write-report`** relays the tags written per programme and org, and any dropped code.

## Prompts and skills

- `prompts/entity_researcher.md`: for each programme, the themes, populations and lenses its own
  description supports. Tags on `identity` or `org_identity` only when the source states a focus for the whole organisation.
- `ngo-credential-research` and `funder-intake-research` name the step in their source order.
  `catalog-mapping` maps a programme's tags to `program_tags` and a stated focus to `org_tags` or `funder_tags`.
- The research rubric is unchanged: the schema already refuses a tag without its `tag_note`.

## The 7 orgs already on staging

Their programmes exist untagged. Re-running Import on each with its own sources is the honest
backfill, because tags then cite what was read. No one-off tagging script.

## Tests

- **Schema:** an unknown code is kept (lower-cased, de-duplicated) for the writer to drop; the schema
  offers the codes; a tag without `tag_note` is refused; more than three themes is refused.
- **Writer** (integration): codes land as inferred `sangam-import` tags with the note, a missing code
  goes to `reasons`, and a rerun adds nothing.
- **Vocabulary:** the backend copies equal the seed files, and theme and sub-theme codes never collide.
- **End to end** (run by hand against a scratch database): an org research row with an
  `org_identity` focus and a tagged programme, through `promote()`, writes 2 `org_tags` and 4
  `program_tags`, with nothing held. The match-v2 tests already cover how those tags score.

## Decisions (2026-10-11)

1. **Tags count straight away,** marked `is_inferred`; no confirmation step.
2. **Lenses stay descriptive:** recorded, never scored.
3. **No tag editing on the profile page** for now.
4. **An invented code is dropped and noted,** never a reason to refuse the save.

The 12 saved staging matches (match-v1) are not rerun automatically; a person reruns one when needed.

## Known limits

- A funder's programme tags are written to `program_tags`, but match-v2 reads only `funder_tags`
  and the activity lines, so they do not affect matching yet.
- A plan (the Gate's preview) writes no tags, so the before-and-after does not show them.
- Before this deploys: `make migrate ENV=staging` (after a backup) applies 0043. Without it tags
  still write, but undo cannot remove them.
