# Import writes themes, populations and lenses

Status: proposal, 2026-10-11. Step 2 of the bulk-load plan. It depends on match-v2
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
| Org | `org_tags` | a new `focus` finding: the org's stated focus, when the source states one beyond its programmes |
| Funder | `funder_tags` | the same `focus` finding: the stated focus in a CSR policy or foundation page. Spend lines stay as they are |

What can be tagged, all from the closed taxonomy (`seed/data/taxonomy/`):
- **Themes:** a sub-theme code, or a theme code when only the broad area is clear. Never a domain
  alone: the domain follows from the theme.
- **Populations:** codes from `common.json` `population`.
- **Lenses:** codes from `themes.json` `lenses`. They are recorded but not scored in match-v2.

## Shape

`ProgramFinding` gains three fields, and a new `FocusFinding` (`concept: "focus"`) carries the same
three for an org or a funder:

```python
themes: list[ThemeCode] = []        # Literal of every theme and sub-theme code, built from themes.json
populations: list[PopulationCode] = []
lenses: list[LensCode] = []
tag_note: str | None                # required when any list is non-empty: the words it rests on
```

- **The vocabulary lives in the schema.** The `Literal`s are built from the seed files when the
  module is imported, so the researcher's structured-output schema enumerates the allowed codes. That
  avoids a second copy in a prompt (prompt substitution is reserved for `MAX_PARALLEL_RESEARCH`), and
  pydantic refuses an invented code.
- **At most three themes per programme or focus.** That forces a primary reading over a scatter of
  tags.
- **`tag_note` is required,** like a spend line's `classification_note`. A tag is an inference, and
  it names its evidence, for example "programme page: 'women's SHG federations in Udalguri'".

## Writing

- `writer.write_program_tags(conn, program_id, codes, note)` and `write_entity_tags(conn, owner, codes, note)`
  resolve each code against `tags` with `status <> 'deprecated'`.
  - A code not in `tags` means the seed is behind. It goes to `report["reasons"]`, never inserted.
  - They write `role='primary'`, `is_inferred=true`, `tagged_by='import'` and the note.
- **Additive, like everything Import writes.** A re-import adds tags and never removes one a person
  set (`tagged_by <> 'import'`).
- **Plan mode** skips the write, as `write_funder_tag` does.
- **Logged in `catalog_writes`,** so staff can undo the save.
- **`catalog-write-report`** relays the tags written per programme and org, and any refused code.

## Prompts and skills

- `prompts/entity_researcher.md`: for each programme, the themes, populations and lenses its own
  description supports. For an org or funder, a `focus` finding only when the source states a focus.
- `ngo-credential-research` and `funder-intake-research` name the step in their source order.
  `catalog-mapping` maps `focus` to `org_tags` or `funder_tags`.
- The research rubric (`prompts/research_rubric.md`) checks that every tag has a `tag_note` quoting
  its source.

## The 7 orgs already on staging

Their programmes exist untagged. Re-running Import on each with its own sources is the honest
backfill, because tags then cite what was read. No one-off tagging script.

## Tests

- **Schema:** an unknown code is refused; a tag without `tag_note` is refused; more than three
  themes is refused.
- **Writer:**
  - codes resolve to the right tags;
  - a deprecated or missing code goes to `reasons`;
  - a re-import is idempotent and leaves a person's tags alone.
- **End to end:**
  - a programme tagged `institution-building` against a funder whose spend line is under
    `shg-empowerment` scores theme 25 in `compare_fit`;
  - a funder whose only theme is a CSR clause scores 15.

## Open questions

1. Should a person confirm tags in Import's Done step before they count, or count straight away
   with `is_inferred=true` shown? (Proposed: count straight away, show them, and allow removal.)
2. Should lenses be scored in a later rubric, for example as a bonus inside population, or stay
   descriptive?
3. Should staff be able to edit tags on the profile page? That is a UI change, so it needs a mock
   first.
