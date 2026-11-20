import { redirect } from "next/navigation";
import { apiGet } from "@/lib/api";
import type {
  FunderListItem,
  MeOut,
  OrgListItem,
  PageOf,
  PartnerLineRow,
  ScoreRow,
} from "@/lib/api";
import type { IndexPayload } from "@/features/ask/AskWorkspace";
import { activityEntry, orgEntry, scoreEntry } from "@/features/ask/lib/indexRows";
import { AskPreview } from "@/features/ask/preview/AskPreview";
import { canUseScout } from "@/features/ingest/lib/access";
import { WorkspaceLoader } from "@/features/ask/WorkspaceLoader";
import { cookies } from "next/headers";
import { DEV_COOKIE, DEV_LOGIN } from "@/lib/devAuth";
import { createClient } from "@/lib/supabase/server";

export const metadata = { title: "Ask Sangam" };

export const dynamic = "force-dynamic";

async function isSignedIn(): Promise<boolean> {
  if (DEV_LOGIN) return Boolean((await cookies()).get(DEV_COOKIE)?.value);
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
  // Import was a view here once; old links go to its own page.
  if (params.view === "import") redirect("/import");
  if (!(await isSignedIn())) return <AskPreview initialQuestion={q} />;

  const [orgs, funders, scores, lines, stats, me] = await Promise.all([
    apiGet<OrgListItem[]>("/api/orgs"),
    apiGet<FunderListItem[]>("/api/funders"),
    apiGet<PageOf<ScoreRow>>("/api/scores?limit=100").then((p) => p.items),
    apiGet<PageOf<PartnerLineRow>>("/api/partner-lines?limit=100").then((p) => p.items),
    apiGet<Record<string, number>>("/api/meta/stats"),
    apiGet<MeOut>("/api/me").catch(() => null),
  ]);

  const funderSlugById = new Map(funders.map((f) => [f.id, f.slug]));

  // Provenance travels with the index so the workspace can say where a cited row came from
  // without a second round trip.
  const payload: IndexPayload = {
    orgs: orgs.map(orgEntry),
    funders: funders.map((f) => ({
      id: f.id,
      slug: f.slug,
      name: f.name,
      sourceUrl: f.source_url,
      sourceName: f.source_name,
      fetchedAt: f.fetched_at,
    })),
    scores: scores.map((s) => scoreEntry(s, funderSlugById.get(s.funder_id))),
    activities: lines.map(activityEntry),
    stats,
    canScout: me ? canUseScout(me) : false,
    me,
  };

  // The workspace fills the viewport below the sticky navbar; the footer sits below the fold.
  return (
    <div data-app-shell style={{ height: "calc(100dvh - var(--nav-h))", display: "flex", flexDirection: "column" }}>
      <WorkspaceLoader payload={payload} initialQuestion={q} />
    </div>
  );
}
