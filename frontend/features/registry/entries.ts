/* View model for the Registry screen: one list mixing CSOs and funders.

   This is presentation, not transport — it decides what a row says when a
   field is missing, which is why it lives with the feature rather than in
   lib/api. */

import { titleCase } from "@/lib/format";
import type { FunderListItem, OrgListItem } from "@/lib/api";

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
    meta: org.darpan_id ? `Darpan ${org.darpan_id}` : `Source: ${org.source_name ?? "vetting"}`,
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
