/* Server-side data access to the FastAPI backend. */

const BASE =
  process.env.AGENT_URL?.replace(/\/agent$/, "") ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8010";

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { Authorization: "Bearer dev" },
    cache: "no-store",
  });
  if (res.status === 404) throw new NotFoundError(path);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

export class NotFoundError extends Error {
  constructor(path: string) {
    super(`not found: ${path}`);
  }
}

/* Shapes returned by the legacy array endpoints. */
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

/* Unified registry entry consumed by the Registry screen. */
export type RegistryEntry = {
  id: number;
  slug: string;
  kind: "CSO" | "Funder";
  name: string;
  where: string;
  blurb: string | null;
  tags: string[];
  meta: string;
  status: "full" | "partial";
  href: string;
  states: string[];
};

export function toRegistryEntries(orgs: OrgListItem[], funders: FunderListItem[]): RegistryEntry[] {
  const orgEntries: RegistryEntry[] = orgs.map((org) => ({
    id: org.id,
    slug: org.slug,
    kind: "CSO",
    name: titleCase(org.name),
    where: [titleCase(org.district), org.state].filter(Boolean).join(", ") || "Location not entered",
    blurb: null,
    tags: org.sectors.slice(0, 4),
    meta: org.darpan_id ? `Darpan ${org.darpan_id}` : `Source: ${org.source_name ?? "hand-vetting"}`,
    status: org.sectors.length > 0 && org.darpan_id !== null ? "full" : "partial",
    href: `/registry/${org.slug}`,
    states: org.state ? [org.state] : [],
  }));

  const funderEntries: RegistryEntry[] = funders.map((funder) => ({
    id: funder.id,
    slug: funder.slug,
    kind: "Funder",
    name: funder.name,
    where: funder.geographies.filter((g) => g !== "India").join(" · ") || "India",
    blurb: (funder.profile?.flagship_program as string) ?? null,
    tags: funder.focus_sectors.slice(0, 4),
    meta:
      Object.keys(funder.latest_scores ?? {}).length > 0
        ? `Scored against rubric ${Object.keys(funder.latest_scores).sort().join(", ")}`
        : "Not yet scored against the cohort",
    status: "full",
    href: `/registry/funders/${funder.slug}`,
    states: funder.geographies.filter((g) => !["India", "Northeast India"].includes(g)),
  }));

  return [...orgEntries, ...funderEntries];
}

export function titleCase(value: string | null): string {
  if (!value) return "";
  if (value !== value.toUpperCase()) return value; // already mixed case — leave as-is
  return value
    .toLowerCase()
    .split(/\s+/)
    .map((w) => (w.length > 2 ? w[0]!.toUpperCase() + w.slice(1) : w.toUpperCase()))
    .join(" ");
}
