import { authHeaders } from "@/lib/api/auth-headers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

export type SaveResult = {
  slug: string;
  entity: {
    kind: string;
    id: number | null;
    name: string;
    status: string | null;
  } | null;
  promotion_id: number | null;
  written: number;
  held: number;
  reasons: string[];
};

/** Save one researched organisation to Sangam with the person's answers; throws the backend's reason when refused. */
export async function saveResearch(slug: string, decisions: Record<string, string>): Promise<SaveResult> {
  const res = await fetch(`${API}/api/ingest/research/${encodeURIComponent(slug)}/save`, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify({ decisions }),
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(body?.detail ?? `Saving failed: ${res.status}`);
  return body as SaveResult;
}
