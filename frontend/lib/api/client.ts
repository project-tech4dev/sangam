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

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: await serverAuthHeaders(),
    cache: "no-store",
  });
  if (res.status === 404) throw new NotFoundError(path);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}
