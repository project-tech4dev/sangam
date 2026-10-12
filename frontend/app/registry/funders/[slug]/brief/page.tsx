import { notFound } from "next/navigation";
import { apiGet, NotFoundError, type FunderProfile } from "@/lib/api";
import { BriefArticle } from "@/features/registry/brief/BriefArticle";
import { parseBrief } from "@/features/registry/brief/parseBrief";

export default async function FunderBriefPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  let profile: FunderProfile;
  try {
    profile = await apiGet<FunderProfile>(`/api/funders/${slug}/profile`);
  } catch (err) {
    if (err instanceof NotFoundError) notFound();
    throw err;
  }
  if (!profile.brief) notFound();

  // The signed URL lasts an hour; the page fetches it fresh rather than caching the text.
  const res = await fetch(profile.brief.url, { cache: "no-store" });
  if (!res.ok) throw new Error(`research brief fetch failed: ${res.status}`);
  const brief = parseBrief(await res.text());
  if (!brief.name) brief.name = profile.funder.name;

  return <BriefArticle brief={brief} slug={slug} rawUrl={profile.brief.url} />;
}
