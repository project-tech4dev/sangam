/* Transport to the FastAPI backend, used from server components. */

import { serverAuthHeaders } from "./auth-headers.server";

const BASE =
  process.env.AGENT_URL?.replace(/\/agent$/, "") ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8010";

export class NotFoundError extends Error {
  constructor(path: string) {
    super(`not found: ${path}`);
  }
}

// A signed-out read is the same for every visitor (RLS as anon), so it can come from Next's data
// cache, refreshed in the background, instead of waiting on a backend that may be starting cold.
// Not in development, where nobody is signed in and a fresh Import save should show at once.
const ANON_REVALIDATE_SECONDS = 300;
const CACHE_ANON = process.env.NODE_ENV === "production";

export async function apiGet<T>(path: string): Promise<T> {
  const headers = await serverAuthHeaders();
  const res = await fetch(`${BASE}${path}`, CACHE_ANON && !headers.Authorization
    ? { next: { revalidate: ANON_REVALIDATE_SECONDS } }
    : { headers, cache: "no-store" });
  if (res.status === 404) throw new NotFoundError(path);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}
