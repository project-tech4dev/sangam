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
  source_url: string | null;
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
  source_name: string | null;
  source_url: string | null;
  fetched_at: string | null;
};

/* Shared sub-shapes. */
export type Identifier = {
  id?: number; id_type: string; id_value: string | null; status: string;
  valid_from: string | null; valid_until: string | null; application_ref: string | null;
  check_method: string | null; verified: boolean; is_current: boolean;
  source_type: string | null; evidence: string | null; source_url: string | null;
};
export type TagRef = { slug: string; label: string; role: string | null };
export type LocationRef = { id: number; kind: string; name: string; role: string | null };
export type Contact = {
  id: number; name: string; role: string | null; kind: string;
  email: string | null; phone: string | null; verified: boolean;
};

/* Detail shapes (v2 API). */
export type OrgDetail = OrgListItem & {
  org_kind: string; legal_form: string | null; registration_date: string | null;
  website: string | null; description: string | null; aliases: string[];
  staff_count: number | null; staff_count_note: string | null;
  source_type: string | null; evidence: string | null;
  contact: Record<string, unknown>; profile: Record<string, unknown>;
  identifiers: Identifier[]; tags: TagRef[]; locations: LocationRef[]; contacts: Contact[];
};

export type FunderDetail = FunderListItem & {
  section_135_bound: boolean | null; cin: string | null; aliases: string[];
  tags: TagRef[]; locations: LocationRef[]; contacts: Contact[];
};

export type ScoreRow = {
  id: number; org_id: number; org_name: string | null; funder_id: number;
  funder_name: string | null; rubric_version: string | null;
  total_score: number; max_score: number; scored_by: string; scored_at: string; notes: string | null;
};

// A funder_activity partner line (grants included); `id` is what [activity:N] cites. Amounts are INR.
export type PartnerLineRow = {
  id: number; funder_id: number; funder_slug: string; funder_name: string; fiscal_year: string;
  partner_name: string; partner_org_id: number | null; partner_org_slug: string | null;
  partner_org_name: string | null; project_name: string | null;
  program_id: number | null; program_name: string | null; amount: number | null;
  start_date: string | null; end_date: string | null; relationship_status: string | null; notes: string | null;
  source_name: string | null; source_url: string | null; fetched_at: string | null;
  fy_is_dated: boolean; // false when fiscal_year is only when the source was read
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
