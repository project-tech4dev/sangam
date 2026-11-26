import { redirect } from "next/navigation";
import { ChangeCheck } from "@/features/ingest/components/ChangeCheck";
import type { Me } from "@/features/ingest/lib/access";
import { apiGet } from "@/lib/api";

export const metadata = { title: "Check for changes · Sangam Scout" };

export const dynamic = "force-dynamic";

// Staff only, like the source checks themselves; anyone else goes back to Scout.
export default async function ChangeCheckRoute({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const me = await apiGet<Me>("/api/me").catch(() => null);
  if (!me?.is_staff) redirect("/import");
  return <ChangeCheck slug={slug} />;
}
