The researcher is done when all of these hold. The `save_research` call appears in the transcript as a digest of its arguments: goals, the concepts found, the gaps and the counts.

1. `save_research` was called and its result starts "Saved as entity_research". A result starting "REFUSED" also passes when the final summary reports the refusal, such as the earlier research being already on file.
2. Every gap has a `reason` of `blocked` or `not_stated` and a `detail` that names the source.
3. When `status` is `partial`, `stopped_reason` says why the research stopped, such as the reading limit or a blocked site.
4. The final summary's `fact_count` equals the number of findings saved, and its `concepts_found` matches the concepts in the save.
5. The final summary's `entity_kind` is `funder` or `org` unless the sources really could not tell.
6. Every programme named in `programs_untagged` has a gap with concept `program`, field `themes` and reason `not_stated`, whose `detail` names that programme and the source read. A programme saved with themes needs nothing. Tagging uses pages already read, so asking for it is not asking for more research.

Do not ask for more research. Reading more is not a revision: judge only whether what was found is saved and reported correctly.

The result is `satisfied` whenever every criterion passes. `needs_revision` needs at least one criterion with `passed: false` and its gap.
