import { apiGet, type RegistryOut } from "@/lib/api";
import { RegistryClient } from "@/features/registry/RegistryClient";

export const metadata = { title: "Registry — Sangam" };

// Filters, including ?type=, are read in the browser from the address.
export default async function RegistryPage() {
  const { rows } = await apiGet<RegistryOut>("/api/registry");

  return (
    <div className="page">
      <RegistryClient rows={rows} />
    </div>
  );
}
