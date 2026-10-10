import { authHeaders } from "@/lib/api/auth-headers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

/** The backend's reason when it refuses, e.g. a row changed since the save. */
async function send(method: string, path: string): Promise<void> {
  const res = await fetch(`${API}${path}`, { method, headers: await authHeaders() });
  if (res.ok) return;
  const body = await res.json().catch(() => null);
  throw new Error(body?.detail ?? `${method} ${path} failed: ${res.status}`);
}

/** Staff: remove what one save added and restore what it changed. Refused, and nothing changes, if a row was edited since. */
export const undoSave = (promotionId: number) => send("POST", `/api/ingest/promotions/${promotionId}/undo`);

/** Staff: delete research that is not saved in Sangam. */
export const deleteResearch = (slug: string) => send("DELETE", `/api/ingest/research/${encodeURIComponent(slug)}`);
