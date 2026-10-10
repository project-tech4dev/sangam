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
  /** Staff only: the save that still stands, and who made it. */
  promotion_id?: number | null;
  saved_by?: string | null;
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

/** One workbook in a bucket; `path` is what choose_sources takes as a staff_path. */
export type Workbook = {
  path: string;
  name: string;
  folder: string;
  folder_label: string;
  size: number | null;
  updated_at: string | null;
};

export type ReviewFact = { label: string | null; value: string | number; money: boolean };

export type ReviewAnswer = {
  concept: string;
  topic: string;
  year: string | null;
  facts: ReviewFact[];
  tag: "confirmed" | "self_reported";
  quote: string;
  source_url: string;
  source_name: string;
  /** From the organisation's own Doc Vault. */
  private?: boolean;
  /** Shown here, and not saved to Sangam. */
  held?: boolean;
};

export type ReviewMissing = { concept: string; topic: string; tag: "not_mentioned" | "couldnt_read"; detail: string };

export type ReviewQuestion = {
  id: string;
  case: number | null;
  topic: string;
  about: string;
  fields: { label: string; old: unknown; new: unknown; money: boolean }[];
  stored_as_of: string | null;
  new_as_of: string | null;
  stored_name: string | null;
  new_name: string | null;
  choices: { value: string; label: string }[];
};

/** GET /ingest/research/{slug}/review: one organisation in staff's words, no table or column names. */
export type ResearchReview = {
  slug: string;
  name: string;
  kind: string | null;
  /** Already in Sangam, so saving only fills empty answers (an NGO) or asks first (a funder). */
  existing: boolean;
  answers: ReviewAnswer[];
  missing: ReviewMissing[];
  questions: ReviewQuestion[];
  saves: { concept: string; topic: string; added: number; updated: number }[];
};
