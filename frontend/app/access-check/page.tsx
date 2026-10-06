import { AccessCheckPage } from "@/features/access-check/AccessCheckPage";

export const metadata = { title: "Access check — Sangam" };
export const dynamic = "force-dynamic";

export default async function AccessCheck({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const { tab } = await searchParams;
  return <AccessCheckPage tab={tab === "public" || tab === "flag" || tab === "staff" ? tab : "access"} />;
}
