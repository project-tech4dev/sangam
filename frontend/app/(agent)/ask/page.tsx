import { apiGet } from "@/lib/api";
import { titleCase } from "@/lib/format";
import type {
  FunderListItem,
  GrantRow,
  OrgListItem,
  PageOf,
  ScoreRow,
} from "@/lib/api";
import type { IndexPayload } from "@/features/ask/AskWorkspace";
import { AskPreview } from "@/features/ask/preview/AskPreview";
import { WorkspaceLoader } from "@/features/ask/WorkspaceLoader";
import { createClient } from "@/lib/supabase/server";

export const metadata = { title: "Ask Sangam" };

export const dynamic = "force-dynamic";

async function isSignedIn(): Promise<boolean> {
  try {
    const supabase = await createClient();
    const { data } = await supabase.auth.getClaims();
    return Boolean(data?.claims);
  } catch {
    // No Supabase keys (a bare local run): nobody can sign in, so show the preview.
    return false;
  }
}

// One URL: signed out it is a preview that costs no agent call, signed in the workspace.
// `?q=` carries a question from elsewhere (a Registry profile's "Ask Sangam about …").
export default async function AskPage({ searchParams }: { searchParams: Promise<{ q?: string; view?: string }> }) {
  const params = await searchParams;
  const q = params.q?.trim().slice(0, 500) || null;
  // Only Tools are addressable by URL; chat views are not.
  const initialView = params.view === "import" ? "import" : "ask";
  if (!(await isSignedIn())) return <AskPreview initialQuestion={q} />;

  const [orgs, funders, scores, grants, stats] = await Promise.all([
    apiGet<OrgListItem[]>("/api/orgs"),
    apiGet<FunderListItem[]>("/api/funders"),
    apiGet<PageOf<ScoreRow>>("/api/scores?limit=100").then((p) => p.items),
    apiGet<PageOf<GrantRow>>("/api/grants?limit=100").then((p) => p.items),
    apiGet<Record<string, number>>("/api/meta/stats"),
  ]);

  const funderSlugById = new Map(funders.map((f) => [f.id, f.slug]));
  const orgSlugById = new Map(orgs.map((o) => [o.id, o.slug]));

  // Provenance travels with the index so the workspace can say where a cited row came from
  // without a second round trip. A score has none: it is Sangam's own rubric judgement.
  const payload: IndexPayload = {
    orgs: orgs.map((o) => ({
      id: o.id,
      slug: o.slug,
      name: titleCase(o.name),
      sourceUrl: o.source_url,
      sourceName: o.source_name,
      fetchedAt: o.fetched_at,
    })),
    funders: funders.map((f) => ({
      id: f.id,
      slug: f.slug,
      name: f.name,
      sourceUrl: f.source_url,
      sourceName: f.source_name,
      fetchedAt: f.fetched_at,
    })),
    scores: scores.map((s) => ({
      id: s.id,
      funderSlug: funderSlugById.get(s.funder_id) ?? String(s.funder_id),
      orgName: s.org_name ?? `org #${s.org_id}`,
      funderName: s.funder_name ?? `funder #${s.funder_id}`,
      rubricVersion: s.rubric_version,
    })),
    grants: grants.map((g) => ({
      id: g.id,
      orgSlug: orgSlugById.get(g.org_id) ?? String(g.org_id),
      title: g.title,
      sourceUrl: g.source_url,
      sourceName: g.source_name,
      fetchedAt: g.fetched_at,
    })),
    stats,
  };

  // The workspace fills the viewport below the sticky navbar; the footer sits below the fold.
  return (
    <div data-app-shell style={{ height: "calc(100dvh - var(--nav-h))", display: "flex", flexDirection: "column" }}>
      <WorkspaceLoader payload={payload} initialQuestion={q} initialView={initialView} />
    </div>
  );
}
