# Sangam Import: from a public source to a catalog row

An agent that finds funder information in permitted sources, matches it against the catalog, and
writes what is safe to write. Separate from Ask Sangam in every respect: its own graph, its own
endpoint (`/ingest`), its own UI, its own instructions, its own trace name (`sangam_import`).

Ask Sangam reads the catalog. This one builds it.

## The rule everything else follows from

**The model never writes SQL.** Ask Sangam's safety story is that model-authored SQL is read-only
and regenerated from an AST; an importer that emitted `INSERT`s would reverse it. Here the model's
only write-shaped output is a **typed record** — a pydantic object with named fields — and
`app/ingest/writer.py` performs the upsert with fixed SQL. The model decides what a source says
and how it maps; it cannot decide which table or which row.

## The two paths

There are two ways data reaches the catalog. They share the matcher and the writer, and nothing
else.

```
  ┌─ RESEARCH PATH (the main one) ────────────────────────┐
  │  entity-researcher, one per organisation:             │
  │    research_goals  what the schema expects, minus     │
  │                    what the catalog already holds     │
  │         ↓                                             │
  │    search_public_sources → read_page / fetch_document │
  │         ↓                                             │
  │    save_research → entity_research (typed findings)   │
  │         ↓                                             │
  │  catalog-writer, one per organisation:                │
  │    promote_research ──────────────────┐               │
  └───────────────────────────────────────│───────────────┘
                                          │
  ┌─ ADAPTER PATH ────────────────────┐   │
  │  run_import_now → india_csr/gdelt │   │
  │         ↓                         │   │
  │  extractor → typed records ───────┼───┤
  └───────────────────────────────────┘   │
                                          ↓
                    matcher.py    identifier → exact → alias →
                                  boilerplate → trigram → queue
                                          ↓
                    geography.py  "Barpeta, Assam" → location_id
                                          ↓
                    writer.py     fixed SQL upsert, provenance required
                                          ↓
                    the catalog   + ingest_run_items (adapter path only)
```

**The research path** answers a question like "profile SBI Foundation for a fundraiser". It reads
whatever the access rules permit, and its intermediate product is durable: `entity_research`, one
row per organisation per day, holding every finding with the sentence that states it.

**The adapter path** is a pull from a source with code written for it. Only two exist — India CSR
and GDELT. It writes straight through and logs every record to `ingest_run_items`.

## Sources: access rules are config, not comments

Every source carries the rule that governs it and the evidence for that rule — `access_rule`,
`basis`, `robots_checked_at`. The inventory is **79 sources** in
`backend/app/ingest/data/sources/*.json`, across four overlapping categories:

| Category | Sources | Dispatchable |
|---|---:|---:|
| funder | 35 | 8 |
| ngo | 26 | 3 |
| rfp | 11 | 2 |
| media | 26 | 15 |

It lives inside the package because the Dockerfile copies only `app/`, and it is JSON so it can be
reviewed by someone who does not write Python. `sources.py` runs a `_self_check()` at **import**
that raises on a duplicate key, a missing category, an unknown yield kind, or a basis short enough
to be a verdict rather than evidence. An access rule is a security decision, so it changes in a
pull request, never at runtime.

Only `open_api` and `crawl_allowed` are dispatchable. Everything else is reported as **refused**,
with its basis, so "give.do: terms bar data mining" is a row in the report rather than a crawl
that should never have happened.

A source is a **product, not a host**: `mcacdm.nic.in` carries several. `rule_for_url()` resolves
a URL to the **strictest** rule among its host's products, so declaration order can never decide
whether a crawler runs.

**Two rules are path-scoped**: `manual_aggregator` (Give.do's `/discover/` pages, GuideStar India's
public search method) and `internal_research` (the team's org-grant-intelligence repository at one
pinned commit, and its directory listings). Neither is dispatchable; the researcher's fetch tools
read them one URL at a time. An entry names its exact host, `allowed_paths` (a prefix ending in `/`
needs a segment below it; anything else is exact) and `allowed_query` (the keys allowed, each with
a pinned value or any). The URL checked is the one httpx sends (`str(httpx.URL(url))`), so the host
is IDNA-encoded (`give。do` is `give.do`), lower-cased and its trailing dot dropped; the path is
decoded once with `.`, `..` and `//` resolved, and a path still encoded after that, a `;`, a
backslash, a user name, a port, plain http or a sign-in segment is refused. A path the entry does
not claim keeps the host's strictest other rule (`give.do/api/` stays `no_scraping`), and robots.txt
is still asked for one it does: unreadable robots.txt refuses a path-scoped read (fail closed).
`read_page` and `fetch_document` run the same check on every redirect hop before requesting it.
`source_guards.py` makes every value from these sources `claimed`, as `aggregator` or
`prior_research`, at save and again at promote, where a finding whose table cannot mark it claimed
is held.
The repository's other copies (github.com, codeload, jsDelivr) are refusing entries that govern
only the repository's path (`governs_paths`), and a value citing any of them is still
`prior_research`.

**No fetch reaches a private address.** `app/core/egress.py` refuses loopback, private, link-local,
metadata, `localhost`, single-label hosts and any literal form of them (`2130706433`,
`[::ffff:127.0.0.1]`), then resolves the name and refuses if any address is not global. It runs
on every redirect hop for the research tools, `fetch_url` and robots.txt. It does not pin the
resolved address for the connection, so a name that rebinds between check and connect is not
caught. A NAT64 address (`64:ff9b::/96`) is judged by the IPv4 address in its last 32 bits.

Three states, and they are not the same thing:

| | Count | Meaning |
|---|---:|---|
| **pulls** | 2 | permitted *and* an adapter exists — India CSR, GDELT |
| **permitted, not built** | 20 | legally readable, nothing reads it yet. Not a failure |
| **held** | 57 | its rule forbids it; the basis says what would unblock it |

`read_page` and `fetch_document` check twice before fetching: the registry decides the site,
`robots.txt` decides the path. RFC 9309 semantics — a 4xx on robots means allow, a 5xx or an
unreadable one means refuse. Crawl etiquette lives in the adapter rather than in the operator's
head: one request at a time per host, a `Sangam/0.1` user agent, and `documents.content_hash` so a
re-run does not re-fetch an unchanged page.

**A host read but not registered becomes a proposal.** `ingest_source_proposals` records it with
what robots said and how often it has been seen. That is a note, never a permission: promoting it
means adding it to the JSON with a basis and a robots check, in a pull request.

## The agents

One main agent and two subagents, built in `app/ingest/agent.py`.

**Every tool lives in `app/ingest/tools/`, and nothing else in `app/ingest/` is a tool** — the
rest of the folder is the pipeline the tools drive. Three modules, by what the tool touches,
mirroring `app/agent/tools/` on the Ask Sangam side:

| Module | Tools |
|---|---|
| `pipeline_tools.py` | `list_import_sources` · `plan_import` · `run_import_now` · `import_run_summary` · `pending_resolutions` · `list_storage_buckets` · `list_bucket_files` · `select_source_files` · `read_source_rows` · `read_workbook` |
| `catalog_tools.py` | `research_goals` · `funder_dossier` · `promote_research` · `record_registry_check` |
| `research_tools.py` | `search_public_sources` · `read_page` · `fetch_document` · `read_document_pages` · `save_research` · `publish_brief` |

**Sangam Import** (main) holds eight: the five pipeline tools, `funder_dossier`,
`record_registry_check` and `publish_brief`. It supervises. It cannot open a web page, and the
only catalog row it writes is a staff member's own registry check (`app/ingest/manual_checks.py`:
checker from the chat's user, ranked as `manual_check`, evidenced only with a document of that
organisation). Research and promotion go through a subagent, so there is one path to a source
and one path from research to the catalog, each under the prompt written for it. The parent held all of them until 2026-10-03, and a
single-organisation run then researched under `instructions.md`, without the researcher's
budget, entity-confirmation or money-unit rules: two paths to the same work, already drifted.

`research_goals` went with them. In a kind-aware world it refuses `"unknown"`, and a supervisor
that has not read a source can only ever guess `"funder"`.

A tool's **prompt** is therefore whichever one owns its list. An isolated subagent never sees
`instructions.md`, so naming a researcher's tool there does nothing for it;
`test_a_subagent_prompt_names_every_tool_its_spec_declares` holds each spec against its own
`prompts/<name>.md`.

**`entity-researcher`** — one per organisation, `mode: "isolated"`, so each gets its own context
window. The reason is context, not speed: a single broad turn once read three PDFs across twenty
tool calls and never reached its report, because each document displaced the last one's findings.
An isolated subagent returns its conclusion, not its reading. It hands back a thin
`ResearchSummary` — counts and status, not the findings, which it has already saved itself.

**Picking the workbooks, with a person in the loop.** The supervisor lists the buckets
(`list_storage_buckets`), then the `.xlsx` files in one (`list_bucket_files`), and proposes a pick
with `select_source_files(paths)`. Both `list_bucket_files` and `select_source_files` are in
`INTERRUPT_ON` (`app/ingest/agent.py`), which deepagents turns into LangChain's
`HumanInTheLoopMiddleware`: the run pauses twice, the Import screen shows `BucketPicker` then
`SourcePicker` through CopilotKit's `useInterrupt`, and staff approve, edit (another bucket,
other files) or reject. The resume is `{decisions: [...]}`, delivered as `Command(resume=…)`. On approval
the tool downloads each file, writes its `documents` row (`extractor_version
'select_source_files/1'`) and returns the document ids the researchers' tasks carry. Any
bucket's `.xlsx` is selectable, at any depth; a first folder named for a registry key also names
the source (and its unit). A file
dropped in through the Supabase dashboard therefore works with no script; `make staff-source`
still writes the same row.

**`workbook-reader`** — for a request about everyone in a file ("research every funder in the CSO
workbook"), where there is no name to give a researcher. Isolated, one tool: `read_workbook`
(an outline of every sheet, then pages of rows, with the same markers and redaction as
`read_source_rows`). It returns `WorkbookEntities` — names, kinds and the marker of each name's
cell — and the supervisor launches a researcher per name. The supervisor itself never reads a row.

**Staff workbooks.** `read_source_rows` is the researcher's eighth tool (the supervisor does not
have it). It reads the workbooks staff picked (its `documents` argument; all registered ones
without it) from Storage with openpyxl and returns header rows and matching rows as
`cell=value`, each cited `[source:<document>#<sheet>!<cell>]`. There is no layout parser: how each
sheet is laid out, and its unit, is in the researcher's prompt under "The staff sheets". On a sheet
of side-by-side blocks (a sparse title row over a dense header row), a matched row shows only the
cells of the block its match sits in, so one CSO's funders never appear on another's line. **Staff
rows last:** `StaffLastLock` (`app/agent/middleware.py`) refuses `search_public_sources`,
`read_page` and `fetch_document` once a run has called `read_source_rows`, so an injected page
cannot have a staff row carried out in a URL or query. Contact columns are dropped. Promoted facts
are public (D14); the files and their `documents` rows stay staff-only, and `promote` holds a staff
finding without its marker. It also re-opens the workbook and holds any staff amount that its cited
row does not print, in the unit it was saved in: the cell's own unit (`12 Lakhs`, `3Cr`) when it
states one, crore for the filing exports (`staff_sources.SOURCE_UNITS`), and the number alone
otherwise (`hold_mismatched`). Tool output reaches the model provider and, with tracing on, Langfuse,
like every tool output.

**`catalog-writer`** — one per organisation, launched after the researchers report. Its only tools
are `promote_research` and `funder_dossier`. It cannot research and cannot author a value: it
promotes, reads the dossier back, and reports the difference. A promotion claiming six rows
against a dossier showing none is the failure worth catching, and nothing else was catching it.

Parallel `task` calls resolve together, so the writers start after the *slowest* researcher, not
one by one.

**Waves, not a cap.** `MAX_PARALLEL_RESEARCH` (default 8) is how many researchers run at once;
ask for thirty organisations and the agent runs four waves, not a list trimmed to eight. It used
to say *"research the first six and tell the user what is left"*, which quietly turned a list of
twenty into a list of six. The number is bounded by connections rather than by ambition — each
researcher holds one from a pool shared with the checkpointer — so `DB_POOL_MAX_SIZE` (default
10) is raised with it, and both are logged at boot. Each subagent gets its own recursion budget,
so the count is not bounded by `RECURSION_LIMIT`; the ceiling that remains is the model
provider's rate limit.

## The research path in detail

**0. One search, to resolve and classify.** Before any budget is spent, the researcher
confirms the organisation is the one that was asked for, and decides whether it **gives**
money or **receives** it. That is `entity_kind`, and it is the most consequential call of
the run: the two kinds get different tables, and an NGO aimed at the funder tables is offered
an identifier enum with no 12A, no 80G and no FCRA. A wrong *entity* is a STOP; a wrong
*kind* is just a different goal list.

**1. `research_goals(name, entity_kind, years)`** — the first call after that. `entity_kind`
is required and `'unknown'` is refused: it stays a save-time value for `not_found` and
`wrong_entity` rows, where it is true, and is never a research target. The tool derives what to
look for from `app/agent/tools/sql/catalog.py`, the same data the SQL tool allowlists and that
`verify_against_db()` checks against the live schema at boot. Per concept it returns the fields a
source could state, their CHECK-constraint values, which of them the row cannot be written
without, and what the catalog already holds. There is no second list of research targets to keep
in sync with the schema.

**2. Research**, strongest source first — a statutory filing or annual report before a news
article. `search_public_sources` marks each hit READABLE or HELD, and a HELD result is a dead end,
not an obstacle: never look for another route to withheld content.

**3. `save_research`** validates and persists. Findings are **typed per concept** — one pydantic
model per target table, its fields named for that table's columns. A finding used to be a `label`
and a `value`, both strings, and promotion bridged the gap with regular expressions: sniffing for
the word "crore" to decide a scale, grepping a label for a fiscal year. That is how a figure
becomes wrong by a factor of ten million, which this codebase shipped twice. Validation happens at
the tool boundary, so a bad finding comes back as an error the model can correct rather than
losing the whole task.

Saving is an upsert on `(slug, date)`. It refuses when the stored result has more findings than
the one offered — a short re-run silently replacing a long one has already cost fifteen findings.

It also **publishes the brief** — `brief.py` renders the row it just wrote and uploads it to
`entities/<slug>.md` in `source-archive`, which is what the funder page's "Research brief" link
serves. That used to wait for someone to run `make client-docs` on the host, so between a
research turn and the next time a person remembered, the page's "Research brief" link pointed
at nothing. Publishing is silent either way, like archiving — the model cannot act on a storage failure and the findings are saved
regardless. `publish_brief(slug)` re-publishes; `make client-docs` is still the only thing that
writes `docs/entities/`, because the container cannot write a repo file and should not.

**4. `promote_research`** maps fields to columns. Documents are written first, so every fact can
cite the report it was read from; then programmes, parents before children, because six concepts
resolve a `program_name` to a `program_id` and a programme written afterwards leaves nulls behind
it.

## What lands where

Seventeen concepts, every one with a writer — a funder is researched against thirteen of them
and an NGO against nine, with five shared. The tables below are a copy; the source is
`CONCEPTS` in `app/ingest/expectations.py`, from which the table map, the brief's section
titles, the promotable list, the "researched but not written" excuses and `concepts_for(kind)`
are all derived.

A **funder** (13):

| Concept | Table |
|---|---|
| identity | `funders` |
| csr_year | `funder_csr_years` |
| csr_spend | `funder_activity`, `kind='spend'` |
| footprint | `funder_activity`, `kind='footprint'` |
| stated_geography | `funder_locations` |
| partner (grants included) | `funder_activity`, `kind='partner'`, from either side |
| programme_spend | `funder_activity`, `kind='programme'` |
| eligibility_guideline | `documents`, `doc_type='funder_eligibility'` |
| program | `programs` |
| metric | `metrics` |
| contact | `contacts` |
| document | `documents` |
| rfp | `rfps` |

Several concepts share one table. `ConceptSpec.row_filter` names the rows each owns and `ConceptSpec.columns` the columns it may fill; `expected_fields()`, `research_goals` and the writers read both.

An **org** (9). `program`, `metric`, `contact` and `document` are the same four tables as
above, which each carry an `org_id` as well as a `funder_id`; only the foreign key changes.
`partner` is each funder that gave the NGO money, written as that funder's partner line.
The other four are the NGO's own:

| Concept | Table |
|---|---|
| program · metric · contact · document | as above, on `org_id` |
| partner | `funder_activity`, `kind='partner'`, on the funder named by `funder_name` with `partner_org_id` = the NGO; held when Sangam does not hold that funder |
| org_identity | `orgs` |
| org_identifier | `org_identifiers`, one row per registration with a `status`; an `applied` row needs no number. 12A, 80G and FCRA live here |
| org_financials | `org_financials` |
| org_location | `org_locations`, and the `registered` one sets `orgs.registered_location_id` |

**On an org the catalog already holds, promotion fills blanks only.** A column is written
where it is NULL and nowhere else; every difference between a stated catalog value and the
research is reported for a person instead. The funder side is the other way round — a stated
value wins — because funder rows are machine-made and the ten cohort orgs were vetted by
hand.

`org_tags` is deliberately unmapped: `tag_id` is a bare `_id`, so the concept would have no
field naming its own subject. The org concepts are namespaced because `Finding` is a tagged
union on `concept` and two members cannot both declare `Literal["identity"]`.

A grant is a `partner` finding with `project_name`, `amount`, `start_date`, `end_date` and
`relationship_status` (`0034` folded the `grants` table into these lines). A funder's research
links the line to an organisation only on a merging match, never a trigram one; an NGO's research
writes the line on a funder Sangam holds and holds it otherwise. `grant` findings saved before
`0034` are promoted as the partner findings they are now.

**`stated_geography` and `footprint` are two concepts on purpose.** Where a funder *says* it
prioritises is not where money demonstrably went. Collapsing them destroys the distinction the
whole agent runs on.

## Four things the writer refuses

Each is reported with its reason, never logged and dropped.

**A place that is not an Indian state.** `geography.py` holds the 28 states and 8 union
territories under the spellings reports actually print — Orissa, NCT of Delhi, Pondicherry,
Tamilnadu. Districts are created on first sight under their stated state, because no offline list
of 780 exists to check against; states never are, because a typo that becomes a state row is wrong
for good and nothing in the schema would flag it. A district always travels with its state:
several states have a Bishnupur.

**A name that resembles one we hold without matching it.** The matcher runs identifier → exact →
alias → boilerplate → trigram → queue, and only the first four merge. Step five proposes and a
person accepts, because a Graphiti spike once merged Christian Medical College, Vellore into the
registry org Better Life Foundation. "Axis Bank" and "Axis Bank Limited" resolve; "Tata Trusts"
and "Tata Foundation" queue, because there the boilerplate is doing the work of telling them
apart.

**An organisation that is not one organisation.** "NSE-listed companies spent ₹22,212 crore" is a
real sentence with a real number and no funder in it. `reject_if_aggregate()` raises on any record
carrying such a name.

**An NGO promoted as a funder.** Every promotable table hangs off `funders`, so promoting
research with `entity_kind = 'org'` would write an NGO into the funder table — a wrong answer
wearing a catalog citation. The supervisor does not launch a `catalog-writer` for one at all:
`ResearchSummary.entity_kind` is required precisely so it can tell, and spending a subagent to
be handed a refusal is the thing to avoid.

## Amounts

Every amount is `{value, unit, text}` — the number as printed, the unit (`inr`, `lakh`, `crore`),
and the source's own wording kept beside it. `Money.inr` is the only conversion in the ingest
path, and `to_inr()` reads the same table for findings that have been through jsonb. The unit is a
**field**, not something inferred from the text, because inference is what got it wrong twice.

The column contract everywhere is INR. ₹1 crore = 10,000,000.

## Fiscal years

`FY2024-25`, enforced by a CHECK on five tables and by the finding models. "FY 2025" in Indian CSR
reporting means FY2024-25; an ambiguous year returns nothing rather than a guess. Never mix years
in one record — recurrence across years is the signal, and collapsing them destroys it.

## What a run produces

The **adapter path** writes `ingest_runs` (one row per run) and `ingest_run_items` (one per
record) with `status` in `added | updated | matched | queued | failed | refused` and, for an
update, the old and new value. The summary the agent returns is a query over those two tables, so
it reads the same during the run, after it, or a week later.

The **research path** writes `entity_research` and returns a promotion report naming the tables
written, the rows held back with their reasons, and the concepts that stayed research.

## The documents

`make client-docs` renders markdown **from the database, on the host**. Two reasons it is not the
container's job: the backend mounts only `./backend/app`, `./seed` and `./db`, so it cannot see
`docs/` — and a generated doc went missing once already.

- `docs/entities/<slug>.md` — fully generated, one per researched organisation: what was found per
  concept with the evidence sentence and source under each, what was looked for and not found, and
  where it stopped.
- `docs/clients/<ngo>/README.md` — only the blocks between `<!-- generated:x -->` and
  `<!-- /generated -->` are rewritten. Hand-written analysis outside them survives, because a
  generator cannot write "the highest-scoring funder is the inactive one" and should not overwrite
  someone who did.

Rendering is from the database rather than by parsing the markdown back, so the two cannot
disagree.

## Where it plugs in

Three additive insertion points: a second `add_langgraph_fastapi_endpoint(path="/ingest")` in
`app/core/lifespan.py`, a second entry in the CopilotKit runtime's agents map, and
`frontend/features/ingest/` behind `/import`. Ask Sangam is untouched.

The Import screen shows one box per subagent — researchers, then writers nested beneath. A
researcher is finished when its **result arrives**, not when the run ends: `running` is run-wide,
so keying off it made every unfinished researcher read as "done" the moment a run stopped.

## Known gaps

- **Registry checks are not yet their own write.** Since `0033` an org's website, description,
  aliases and staff live on `orgs`, and a registration is an `org_identifiers` row with a `status`
  and validity dates, so nothing here is held for want of a column. What is missing is a tool that
  records a staff registry check (`checked_by`, `checked_at`) apart from research.
- **`repositories/orgs.py::get_org` does not read `org_financials`**, so promoted figures do
  not appear on `/orgs/<slug>` yet.
- **`csr_sector_id` is always NULL.** `tags.kind` allows `'csr_sector'` but no Schedule VII
  taxonomy is seeded to normalise against, so a funder's own wording for a theme stays in `notes`
  rather than being invented into a tag.
- **`archive_url` is written by nothing in the ingest path**, against the provenance convention
  in CLAUDE.md. `content_hash` and `extractor_version` are written (`promote.py`); the hash is
  over the sentence and the URL, so re-reading the same claim is recognisably the same fact.
- **Batch durability** — per-organisation timeouts, resumability and per-organisation status are
  designed and not built.
