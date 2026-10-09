export type ImportSource = {
  key: string;
  name: string;
  host: string;
  access_rule: string;
  basis: string;
  categories: string[];
  yields: string[];
  dispatchable: boolean;
  /** Permitted and built are different things; only these are actually fetched. */
  has_adapter: boolean;
  robots_checked_at: string | null;
};

export type SourceProposal = {
  id: number;
  host: string;
  first_seen_url: string | null;
  robots_result: string | null;
  times_seen: number;
  status: string;
  first_seen_at: string;
  last_seen_at: string;
};

export type ImportRun = {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  added: number;
  updated: number;
  matched: number;
  queued: number;
  failed: number;
  refused: number;
};

export type QueueItem = {
  id: number;
  raw_name: string;
  entity_kind: string;
  source: string | null;
  candidates: { id: number; name: string; score: number }[];
  source_url: string | null;
  created_at: string;
};

export type ResearchRecord = {
  id: number;
  entity_name: string;
  canonical_name: string | null;
  entity_kind: string;
  slug: string;
  status: string;
  stopped_reason: string | null;
  summary: string;
  fact_count: number;
  sources_read: string[];
  not_found: string[];
  researched_at: string;
  saved_at: string | null;
  resolved_org_id: number | null;
  resolved_funder_id: number | null;
};

/** One expected cell: a concept, once per fiscal year asked for a year-bound one. */
export type CoverageCell = {
  year: string | null;
  /** "found", or why not. */
  status: "found" | "not_attempted" | "not_stated" | "blocked" | "not_written";
  detail: string;
};

export type CoverageConcept = {
  concept: string;
  title: string;
  cells: CoverageCell[];
  fields_filled: number;
  fields_total: number;
  held: number;
  extra_years: string[];
  added: number;
  updated: number;
  /** Catalog rows before and after the save; null for an NGO not yet saved. */
  before: number | null;
  after: number | null;
};

/** GET /ingest/research/{slug}/coverage */
export type ResearchCoverage = {
  slug: string;
  /** saved: what the save recorded. planned: a funder's dry run. unsaved: an NGO, which cannot be dry-run. */
  stage: "saved" | "planned" | "unsaved";
  saved_at: string | null;
  /** id is null for a funder a plan would add: nothing to link to yet. */
  entity: { kind: string; status: string; id: number | null; name: string } | null;
  reasons: string[];
  held: string[];
  questions: number;
  facts_before: number | null;
  facts_after: number | null;
  name: string;
  kind: string;
  years: string[];
  write_checked: boolean;
  cells: number;
  found: number;
  fields_filled: number;
  fields_total: number;
  concepts: CoverageConcept[];
};

/** One workbook in a bucket; `path` is what select_source_files takes. */
export type Workbook = {
  path: string;
  name: string;
  folder: string;
  folder_label: string;
  size: number | null;
  updated_at: string | null;
};
