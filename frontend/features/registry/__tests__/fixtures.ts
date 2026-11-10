import type {
  FunderIdentity, FunderProfile, Metric, OrgIdentity, OrgProfile, PartnerGroup, PartnerGroupPage, PartnerLineRow,
  ProfileIdentifier, ProgramNode, RegistryRow, Story,
} from "@/lib/api";

export const registryRow = (over: Partial<RegistryRow> = {}): RegistryRow => ({
  kind: "org", id: 1, slug: "org-1", name: "Org One", funder_type: null, place: "Assam", states: ["Assam"],
  themes: [], populations: [], sdgs: [], csr1: false, has_12a_80g: false, fcra: false, intake_mode: null,
  open_call: false, partners: 0, csr_prescribed: null, csr_year: null, press: 0, social: 0, posts_since: null,
  research_runs: 0, researched_on: null, search: "", ...over,
});

export const program = (over: Partial<ProgramNode> = {}): ProgramNode => ({
  id: 1, name: "Creches", kind: null, parent_id: null, description: null, status: null, start_date: null,
  end_date: null, source_name: null, source_url: null, tags: [], metrics: [], ...over,
});

export const metric = (over: Partial<Metric> = {}): Metric => ({
  id: 1, name: "Children reached", value: 100, target: null, unit: null, period: null, stage: null, method: null,
  program_id: null, place: null, source_name: null, source_url: null, ...over,
});

export const identifier = (over: Partial<ProfileIdentifier> = {}): ProfileIdentifier => ({
  id: 1, id_type: "pan", status: "registered", is_current: true, number_withheld: false, id_value: "AAATK1234K",
  application_ref: null, valid_from: null, valid_until: null, check_method: null, verified: true, source_type: null,
  evidence: null, source_url: null, notes: null, ...over,
});

export const partnerLine = (over: Partial<PartnerLineRow> = {}): PartnerLineRow => ({
  id: 1, funder_id: 1, funder_slug: "f", funder_name: "F", fiscal_year: "FY2024", partner_name: "P",
  partner_org_id: null, partner_org_slug: null, partner_org_name: null, project_name: "Creches", program_id: null,
  program_name: null, amount: 500000, start_date: null, end_date: null, relationship_status: null, notes: null,
  source_name: null, source_url: "https://example.org/ar.pdf", fetched_at: null, fy_is_dated: true, ...over,
});

export const group = (over: Partial<PartnerGroup> = {}): PartnerGroup => ({
  key: "g1", name: "Tata Trusts", org_slug: null, funder_slug: "tata-trusts", lines: [partnerLine()], ...over,
});

export const page = (groups: PartnerGroup[], over: Partial<PartnerGroupPage> = {}): PartnerGroupPage => ({
  groups, total: groups.length, in_registry: 0, has_amounts: true, next_cursor: null, ...over,
});

export const story = (over: Partial<Story> = {}): Story => ({
  id: 1, headline: "Creches open in Dhubri", headline_generated: false, summary: null, published_on: "2026-09-12",
  content_kind: null, is_news: true, scope: null, topic: "", sentiment: null, main_url: "https://news.example/a",
  main_host: "news.example", source_type: null, visibility: null, match_level: "", confidence_level: "",
  channel: "press", also: [], entities: [], places: [], area_reason: null, row_id: 1, about: null, ...over,
});

const facts = {
  programs: [], metrics: [], documents: [], tags: [], sdgs: [], stories: { press: 0, social: 0, posts_since: null },
  research: { runs: 0, latest: null, sources: [] }, hidden_contacts: 0, news: [], brief: null,
};

export const orgIdentity = (over: Partial<OrgIdentity> = {}): OrgIdentity => ({
  id: 1, slug: "kabil", name: "KABIL Trust", legal_form: null, registration_date: null, registered_address: null,
  parent: null, website: null, description: null, aliases: [], staff_count: null, staff_count_note: null,
  district: null, state: null, source_name: null, source_url: null, identifiers: [], contacts: [], ...over,
});

export const orgProfile = (over: Partial<OrgProfile> = {}): OrgProfile => ({
  ...facts, org: orgIdentity(), places: [], financials: [], funders: page([]), ...over,
});

export const funderIdentity = (over: Partial<FunderIdentity> = {}): FunderIdentity => ({
  id: 2, slug: "tata-trusts", name: "Tata Trusts", funder_type: null, website: null, funding_trend: null,
  legal_form: null, founded_year: null, registered_address: null, registered_location: null, parent: null, cin: null,
  section_135_bound: null, intake_mode: null, funds_external: null, typical_duration_months: null,
  grant_size_min: null, grant_size_max: null, aliases: [], source_name: null, source_url: null, contacts: [], ...over,
});

export const funderProfile = (over: Partial<FunderProfile> = {}): FunderProfile => ({
  ...facts, funder: funderIdentity(), partners: page([]), spend: [], csr_years: [], footprint: [], stated: [],
  eligibility: [], open_calls: [], ...over,
});
