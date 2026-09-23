import {
  apiGet,
  titleCase,
  type FunderListItem,
  type GrantRow,
  type OrgListItem,
  type PageOf,
  type ScoreRow,
} from "../lib/api";
import { AskWorkspace, type IndexPayload } from "./AskWorkspace";

export const metadata = { title: "Ask Sangam" };

export default async function AskPage() {
  const [orgs, funders, scores, grants, stats] = await Promise.all([
    apiGet<OrgListItem[]>("/api/orgs"),
    apiGet<FunderListItem[]>("/api/funders"),
    apiGet<PageOf<ScoreRow>>("/api/scores?limit=100").then((p) => p.items),
    apiGet<PageOf<GrantRow>>("/api/grants?limit=100").then((p) => p.items),
    apiGet<Record<string, number>>("/api/meta/stats"),
  ]);

  const funderSlugById = new Map(funders.map((f) => [f.id, f.slug]));
  const orgSlugById = new Map(orgs.map((o) => [o.id, o.slug]));

  const payload: IndexPayload = {
    orgs: orgs.map((o) => ({ id: o.id, slug: o.slug, name: titleCase(o.name) })),
    funders: funders.map((f) => ({ id: f.id, slug: f.slug, name: f.name })),
    scores: scores.map((s) => ({
      id: s.id,
      funderSlug: funderSlugById.get(s.funder_id) ?? String(s.funder_id),
      orgName: s.org_name ?? `org #${s.org_id}`,
      funderName: s.funder_name ?? `funder #${s.funder_id}`,
    })),
    grants: grants.map((g) => ({
      id: g.id,
      orgSlug: orgSlugById.get(g.org_id) ?? String(g.org_id),
      title: g.title,
    })),
    stats,
  };

  return (
    <div className="page" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <div className="eyebrow">Ask Sangam</div>
        <h1 style={{ fontSize: 26 }}>Ask the base, get a cited answer</h1>
      </div>
      <AskWorkspace payload={payload} />
    </div>
  );
}
