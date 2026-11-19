import { redirect } from "next/navigation";
import { ChangeCheck } from "@/features/ingest/components/ChangeCheck";
import type { Me } from "@/features/ingest/lib/access";
import type { ResearchRecord } from "@/features/ingest/lib/types";
import { apiGet } from "@/lib/api";

export const metadata = { title: "Check for changes · Sangam Scout" };

export const dynamic = "force-dynamic";

// Staff only, like the source checks themselves; anyone else goes back to Scout.
export default async function ChangeCheckRoute({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const me = await apiGet<Me>("/api/me").catch(() => null);
  if (!me?.is_staff) redirect("/import");
  const research = await apiGet<ResearchRecord[]>("/api/ingest/research?limit=200").catch(() => []);
  const found = research.find((r) => r.slug === slug);
  return <ChangeCheck slug={slug} name={found?.canonical_name ?? found?.entity_name ?? slug} />;
}
