import { apiGet, type RegistryOut } from "@/lib/api";
import { RegistryClient } from "@/features/registry/RegistryClient";

export const metadata = { title: "Registry — Sangam" };

export default async function RegistryPage({
  searchParams,
}: {
  searchParams: Promise<{ type?: string }>;
}) {
  const { type } = await searchParams;
  const { rows } = await apiGet<RegistryOut>("/api/registry");
  const initialType = type === "cso" ? "org" : type === "funder" ? "funder" : "all";

  return (
    <div className="page">
      <RegistryClient rows={rows} initialType={initialType} />
    </div>
  );
}
