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
