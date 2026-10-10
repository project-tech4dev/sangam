import type { MatchDetail, MatchList, MeOut } from "@/lib/api";
import { authHeaders } from "@/lib/api/auth-headers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

export type RunSummary = { run_id: string; run_at: string; funders_checked: number; tiers: Record<string, number> };

async function call<T>(path: string, method = "GET"): Promise<T> {
  const res = await fetch(`${API}${path}`, { method, headers: await authHeaders() });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(body?.detail ?? `Request failed: ${res.status}`);
  return body as T;
}

export const getMe = () => call<MeOut>("/api/me");
export const getMatches = (org: string) => call<MatchList>(`/api/funder-matches?org=${encodeURIComponent(org)}`);
export const getDetail = (id: number) => call<MatchDetail>(`/api/funder-matches/${id}/detail`);
/** Saves a run as the signed-in person; the backend refuses anyone but staff and the org's stewards and admins. */
export const runMatch = (org: string) =>
  call<RunSummary>(`/api/funder-matches/runs?org=${encodeURIComponent(org)}`, "POST");
