import type { OrgListItem, PartnerLineRow, ScoreRow } from "@/lib/api";
import { titleCase } from "@/lib/format";
import type { IndexPayload } from "../AskWorkspace";

// One mapping for the rows the page loads and the ones a cited answer looks up later.
export const orgEntry = (o: OrgListItem): IndexPayload["orgs"][number] => ({
  id: o.id,
  slug: o.slug,
  name: titleCase(o.name),
  sourceUrl: o.source_url,
  sourceName: o.source_name,
  fetchedAt: o.fetched_at,
});

// A score has no provenance: it is Sangam's own rubric judgement.
export const scoreEntry = (s: ScoreRow, funderSlug: string | undefined): IndexPayload["scores"][number] => ({
  id: s.id,
  funderSlug: funderSlug ?? String(s.funder_id),
  orgName: s.org_name ?? `org #${s.org_id}`,
  funderName: s.funder_name ?? `funder #${s.funder_id}`,
  rubricVersion: s.rubric_version,
});

export const activityEntry = (l: PartnerLineRow): IndexPayload["activities"][number] => ({
  id: l.id,
  // The partner organisation when Sangam holds it, else the funder whose line it is.
  href: l.partner_org_slug ? `/registry/${l.partner_org_slug}` : `/registry/funders/${l.funder_slug}`,
  title: `${l.funder_name} → ${l.partner_name}${l.project_name ? `: ${l.project_name}` : ""}`,
  short: `${l.funder_name} → ${l.partner_name}`,
  sourceUrl: l.source_url,
  sourceName: l.source_name,
  fetchedAt: l.fetched_at,
});
