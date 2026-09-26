import { apiGet, type FunderListItem, type OrgListItem } from "@/lib/api";
import { toRegistryEntries } from "@/features/registry/entries";
import { RegistryClient } from "@/features/registry/RegistryClient";

export const metadata = { title: "Registry — Sangam" };

export default async function RegistryPage({
  searchParams,
}: {
  searchParams: Promise<{ type?: string }>;
}) {
  const { type } = await searchParams;
  const [orgs, funders] = await Promise.all([
    apiGet<OrgListItem[]>("/api/orgs"),
    apiGet<FunderListItem[]>("/api/funders"),
  ]);
  const entries = toRegistryEntries(orgs, funders);
  const initialType = type === "cso" ? "CSO" : type === "funder" ? "Funder" : "all";

  return (
    <div className="page">
      <RegistryClient entries={entries} initialType={initialType} />
    </div>
  );
}
