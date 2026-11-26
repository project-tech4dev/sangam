import { apiGet, type MeOut, type RegistryPage } from "@/lib/api";
import { serverAuthHeaders } from "@/lib/api/auth-headers.server";
import { RegistryClient } from "@/features/registry/RegistryClient";
import { filtersFrom, firstParams, PAGE, registryQuery, type RawParams } from "@/features/registry/filtersUrl";

export const metadata = { title: "Registry — Sangam" };

// Only the first page is rendered here; the browser asks for the rest as the person scrolls or filters.
export default async function RegistryPage({ searchParams }: { searchParams: Promise<RawParams> }) {
  const f = filtersFrom(firstParams(await searchParams));
  // Only a signed-in visitor is asked who they are; a public view costs no extra call.
  const signedIn = Boolean((await serverAuthHeaders()).Authorization);
  const [first, me] = await Promise.all([
    apiGet<RegistryPage>(`/api/registry?${registryQuery(f, 0, PAGE)}`),
    signedIn ? apiGet<MeOut>("/api/me").catch(() => null) : null,
  ]);

  return (
    <div className="page">
      <RegistryClient first={first} staff={me?.is_staff ?? false} />
    </div>
  );
}
