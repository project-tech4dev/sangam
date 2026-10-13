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

export type StoryEntity = {
  kind: "org" | "funder"; id: number; slug: string; name: string;
  stance: string | null; visibility: string; match_level: string; confidence_level: string;
};

export type Story = {
  id: number; headline: string; headline_generated: boolean; summary: string | null;
  published_on: string | null; content_kind: string | null; is_news: boolean; scope: string | null;
  topic: string; sentiment: string | null; main_url: string | null; main_host: string | null;
  source_type: string | null; visibility: string | null; match_level: string; confidence_level: string;
  channel: "social" | "press"; // decided in SQL, the same on the list and the profile
  also: { url: string; host: string; source_type: string }[]; entities: StoryEntity[]; places: string[];
  area_reason: string | null; row_id: number; about: StoryEntity | null;
};

export type StoryPage = {
  items: Story[]; next_cursor: string | null;
  counts: { org: number; funder: number; general: number } | null; last_pull: string | null;
};

export type MeOut = {
  id: string | null; email: string | null; is_staff: boolean; is_anonymous: boolean;
  memberships: { org_id: number; org_slug: string; org_name: string; role: string }[];
};

export type MatchTier = "strong" | "medium" | "weak" | "not_scored";

export type MatchRow = {
  id: number;
  funder: { id: number; slug: string; name: string; funder_type: string | null };
  score: number | null;
  prev_score: number | null; // this funder's score in the run before
  tier: MatchTier;
  card: { reasons: { kind: "fit" | "gap"; criterion: string; text: string }[] };
};

export type MatchList = {
  org: { id: number; slug: string; name: string };
  may_run: boolean; // staff, or a steward or admin of the org
  run: { run_id: string; run_at: string; rubric_version: string; funders_checked: number; earlier_runs: number } | null;
  counts: Record<MatchTier, number>;
  matches: MatchRow[];
};

export type MatchCriterion = {
  code: string; label: string; max: number; points: number | null;
  status: "met" | "partial" | "fail" | "unknown"; note: string; cites: string[];
};

export type MatchDetail = {
  id: number; run_at: string; rubric_version: string;
  detail: {
    summary: string; criteria: MatchCriterion[];
    score: { earned: number; judged_max: number; of_100: number } | null;
    not_judged: string[]; improve: string[];
  };
};

export type PageOf<T> = { items: T[]; total: number; limit: number; offset: number };

/* Profile facts: catalog rows only, each with the source it was read from where the row has one. */
export type TagNote = {
  slug: string; label: string; kind: string | null; role: string | null; note: string | null;
  parent_label: string | null;
};
export type SdgRef = { code: string; label: string };
export type Metric = {
  id: number; name: string; value: number | null; target: number | null; unit: string | null;
  period: string | null; stage: string | null; method: string | null; program_id: number | null;
  place: string | null; source_name: string | null; source_url: string | null;
};
export type ProgramNode = {
  id: number; name: string; kind: string | null; parent_id: number | null; description: string | null;
  status: string | null; start_date: string | null; end_date: string | null;
  source_name: string | null; source_url: string | null; tags: TagNote[]; metrics: Metric[];
};
export type Place = {
  location_id: number; kind: string; name: string; state: string | null; role: string | null;
  note: string | null; program_id: number | null; program_name: string | null;
  source_name: string | null; source_url: string | null;
};
export type FinancialYear = {
  fiscal_year: string; total_income: number | null; program_spend: number | null;
  non_program_spend: number | null; foreign_contribution: number | null; foreign_unspent: number | null;
  is_audited: boolean | null; source_name: string | null; source_url: string | null;
};
export type ProfileDocument = {
  id: number; title: string | null; doc_type: string | null; as_of: string | null;
  source_name: string | null; source_url: string | null;
  links: { program_id: number | null; program_name: string | null; fiscal_year: string | null; pages: string[] }[];
};
export type SpendLine = {
  id: number; program_id: number | null; program_name: string | null; fiscal_year: string;
  amount: number | null; notes: string | null; source_name: string | null; source_url: string | null;
};
export type CsrYear = {
  fiscal_year: string; prescribed_csr: number | null; total_spent: number | null;
  spent_on_projects: number | null; unspent_transferred: number | null; local_area_spent: number | null;
  source_name: string | null; source_url: string | null;
};
export type FootprintState = {
  fiscal_year: string; state: string | null; districts: number; district_names: string[];
  source_name: string | null; source_url: string | null;
};
export type StatedPlace = {
  name: string; kind: string | null; state: string | null; role: string | null; note: string | null;
  source_name: string | null; source_url: string | null;
};
export type EligibilityDoc = {
  id: number; title: string | null; content_md: string | null; source_name: string | null; source_url: string | null;
};
export type OpenCall = {
  id: number; title: string; url: string | null; deadline: string | null;
  amount_min: number | null; amount_max: number | null; source_url: string | null;
};

/* How often Import researched the entity and the public pages it read; counts only. */
export type ResearchTrail = { runs: number; latest: string | null; sources: { url: string; first_read: string | null }[] };

export type EntityRef = { id: number; name: string; slug: string };

/* A registration as every viewer sees it: a private one is on file, with no number or detail. */
export type ProfileIdentifier = {
  id: number | null; id_type: string; status: string; is_current: boolean; number_withheld: boolean;
  id_value: string | null; application_ref: string | null; valid_from: string | null; valid_until: string | null;
  check_method: string | null; verified: boolean; source_type: string | null; evidence: string | null;
  source_url: string | null; notes: string | null;
};
export type ProfileContact = {
  id: number; name: string; role: string | null; kind: string; email: string | null; phone: string | null;
  source_name: string | null; source_url: string | null;
};
export type OrgIdentity = {
  id: number; slug: string; name: string; legal_form: string | null; registration_date: string | null;
  registered_address: string | null; parent: EntityRef | null; website: string | null; description: string | null;
  aliases: string[]; staff_count: number | null; staff_count_note: string | null;
  district: string | null; state: string | null; source_name: string | null; source_url: string | null;
  identifiers: ProfileIdentifier[]; contacts: ProfileContact[];
};
export type FunderIdentity = {
  id: number; slug: string; name: string; funder_type: string | null; website: string | null;
  funding_trend: string | null; legal_form: string | null; founded_year: number | null;
  registered_address: string | null; registered_location: string | null; parent: EntityRef | null;
  cin: string | null; section_135_bound: boolean | null; intake_mode: string | null;
  funds_external: boolean | null; typical_duration_months: number | null;
  grant_size_min: number | null; grant_size_max: number | null; aliases: string[];
  source_name: string | null; source_url: string | null; contacts: ProfileContact[];
};
export type StoryCounts = { press: number; social: number; posts_since: string | null };

/* A funder's partners or an org's funders, a page of groups at a time; totals cover every group. */
export type PartnerGroup = {
  key: string; name: string; org_slug: string | null; funder_slug: string | null; lines: PartnerLineRow[];
};
export type PartnerGroupPage = {
  groups: PartnerGroup[]; total: number; in_registry: number; has_amounts: boolean; next_cursor: string | null;
};

type ProfileFacts = {
  programs: ProgramNode[]; metrics: Metric[]; documents: ProfileDocument[]; tags: TagNote[]; sdgs: SdgRef[];
  stories: StoryCounts; research: ResearchTrail;
  hidden_contacts: number; // non-public contacts on file: a count, never a name
  news: Story[]; brief: { url: string } | null;
};

/** GET /api/orgs/{slug}/profile — everything an org profile shows, in one call. */
export type OrgProfile = ProfileFacts & {
  org: OrgIdentity; places: Place[]; financials: FinancialYear[]; funders: PartnerGroupPage;
};

/** GET /api/funders/{slug}/profile; `brief` is null when no research brief is published. */
export type FunderProfile = ProfileFacts & {
  funder: FunderIdentity; partners: PartnerGroupPage; spend: SpendLine[]; csr_years: CsrYear[];
  footprint: FootprintState[]; stated: StatedPlace[]; eligibility: EligibilityDoc[]; open_calls: OpenCall[];
};

/** GET /api/orgs|funders/{slug}/brief — a signed link to the research brief, with the entity's own slug. */
export type BriefLink = { url: string; expires_in_seconds: number; slug: string; name: string };

/** GET /api/registry — every org and funder the Registry lists, with what its filters and search read. */
export type RegistryRow = {
  kind: "org" | "funder"; id: number; slug: string; name: string; funder_type: string | null;
  place: string | null; states: string[]; themes: { label: string; domain: string | null }[];
  lenses: string[]; sdgs: string[]; csr1: boolean; has_12a_80g: boolean; fcra: boolean;
  intake_mode: string | null; open_call: boolean; partners: number;
  csr_prescribed: number | null; csr_year: string | null;
  press: number; social: number; posts_since: string | null;
  research_runs: number; researched_on: string | null; search: string;
};
export type RegistryOut = { rows: RegistryRow[] };
