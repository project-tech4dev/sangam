/* Row shapes returned by the backend, mirroring backend/app/schemas/.
   Types only — no runtime code, so importing these costs nothing. */

/* Legacy array endpoints. */
export type OrgListItem = {
  id: number;
  slug: string;
  name: string;
  darpan_id: string | null;
  cohort: string | null;
  state: string | null;
  district: string | null;
  sectors: string[];
  source_name: string | null;
  fetched_at: string | null;
};

export type FunderListItem = {
  id: number;
  slug: string;
  name: string;
  funder_type: string | null;
  website: string | null;
  focus_sectors: string[];
  geographies: string[];
  profile: Record<string, unknown>;
  latest_scores: Record<string, number>;
};

/* Shared sub-shapes. */
export type Identifier = { id_type: string; id_value: string; verified: boolean; source_url: string | null };
export type TagRef = { slug: string; label: string; role: string | null };
export type LocationRef = { id: number; kind: string; name: string; role: string | null };
export type Contact = {
  id: number; name: string; role: string | null; kind: string;
  email: string | null; phone: string | null; verified: boolean;
};

/* Detail shapes (v2 API). */
export type OrgDetail = OrgListItem & {
  org_kind: string; legal_form: string | null; registration_date: string | null;
  contact: Record<string, unknown>; profile: Record<string, unknown>;
  identifiers: Identifier[]; tags: TagRef[]; locations: LocationRef[]; contacts: Contact[];
};

export type FunderDetail = FunderListItem & {
  section_135_bound: boolean | null;
  identifiers: Identifier[]; tags: TagRef[]; locations: LocationRef[]; contacts: Contact[];
  source_name: string | null; fetched_at: string | null;
};

export type ScoreRow = {
  id: number; org_id: number; org_name: string | null; funder_id: number;
  funder_name: string | null; rubric_version: string | null;
  total_score: number; max_score: number; scored_by: string; scored_at: string; notes: string | null;
};

export type GrantRow = {
  id: number; funder_id: number; funder_name: string | null; org_id: number; org_name: string | null;
  program_id: number | null; program_name: string | null; title: string;
  amount: number | null; currency: string; start_date: string | null; end_date: string | null;
  status: string; outcomes: Record<string, unknown>; notes: string | null;
  source_name: string | null; source_url: string | null;
};

export type ProgramRow = {
  id: number; org_id: number | null; org_name: string | null; funder_id: number | null;
  funder_name: string | null; name: string; description: string | null; status: string | null;
  details: Record<string, unknown>;
};

export type NewsRow = {
  id: number; url: string; title: string | null; domain: string | null;
  seendate: string | null; topic: string | null;
};

export type PageOf<T> = { items: T[]; total: number; limit: number; offset: number };
