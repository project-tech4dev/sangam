/* Transport to the FastAPI backend, used from server components.

   The bearer token is the dev stub that app/core/security.py accepts from
   anyone; client components send the same literal from their own fetches. */

const BASE =
  process.env.AGENT_URL?.replace(/\/agent$/, "") ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8010";

export class NotFoundError extends Error {
  constructor(path: string) {
    super(`not found: ${path}`);
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { Authorization: "Bearer dev" },
    cache: "no-store",
  });
  if (res.status === 404) throw new NotFoundError(path);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}
