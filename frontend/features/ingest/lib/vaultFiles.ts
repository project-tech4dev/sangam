import { authHeaders } from "@/lib/api/auth-headers";
import type { VaultFile } from "./access";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

type DocumentRow = {
  id: number;
  org_id: number | null;
  title: string | null;
  doc_type: string | null;
  is_public: boolean | null;
};

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { headers: await authHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

/** One organisation's Doc Vault: its private files only. The API returns them to members and staff. */
export async function vaultFilesOf(org: { slug: string; name: string }): Promise<VaultFile[]> {
  const page = await get<{ items: DocumentRow[] }>(`/api/documents?org=${encodeURIComponent(org.slug)}&limit=100`);
  return page.items
    .filter((d) => d.is_public === false && d.org_id !== null)
    .map((d) => ({ id: d.id, title: d.title, doc_type: d.doc_type, org: org.slug, orgId: d.org_id!, orgName: org.name }));
}
