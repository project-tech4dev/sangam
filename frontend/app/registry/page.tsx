import { apiGet, type RegistryPage } from "@/lib/api";
import { RegistryClient } from "@/features/registry/RegistryClient";
import { filtersFrom, PAGE, registryQuery } from "@/features/registry/filtersUrl";

export const metadata = { title: "Registry — Sangam" };

// Only the first page is rendered here; the browser asks for the rest as the person scrolls or filters.
export default async function RegistryPage({ searchParams }: { searchParams: Promise<Record<string, string>> }) {
  const f = filtersFrom(new URLSearchParams(await searchParams));
  const first = await apiGet<RegistryPage>(`/api/registry/page?${registryQuery(f, 0, PAGE)}`);

  return (
    <div className="page">
      <RegistryClient first={first} />
    </div>
  );
}
