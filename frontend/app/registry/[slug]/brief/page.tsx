import { notFound, permanentRedirect } from "next/navigation";
import { apiGet, type BriefLink, NotFoundError } from "@/lib/api";
import { displayName } from "@/lib/format";
import { BriefArticle } from "@/features/registry/brief/BriefArticle";
import { parseBrief } from "@/features/registry/brief/parseBrief";

export default async function OrgBriefPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  let link: BriefLink;
  try {
    link = await apiGet<BriefLink>(`/api/orgs/${slug}/brief`);
  } catch (err) {
    if (err instanceof NotFoundError) notFound();
    throw err;
  }
  if (link.slug !== slug) permanentRedirect(`/registry/${link.slug}/brief`);

  // The signed URL lasts an hour; the page fetches it fresh rather than caching the text.
  const res = await fetch(link.url, { cache: "no-store" });
  if (!res.ok) throw new Error(`research brief fetch failed: ${res.status}`);
  const brief = parseBrief(await res.text());
  brief.name = displayName(brief.name || link.name);

  return <BriefArticle brief={brief} slug={link.slug} kind="org" />;
}
