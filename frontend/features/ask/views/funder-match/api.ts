import type { MatchDetail, MatchList } from "@/lib/api";
import { call } from "../../lib/rest";

export type RunSummary = { run_id: string; run_at: string; funders_checked: number; tiers: Record<string, number> };

export const getMatches = (org: string) => call<MatchList>(`/api/funder-matches?org=${encodeURIComponent(org)}`);
export const getDetail = (id: number) => call<MatchDetail>(`/api/funder-matches/${id}/detail`);
/** Saves a run as the signed-in person; the backend refuses anyone but staff and the org's stewards and admins. */
export const runMatch = (org: string) =>
  call<RunSummary>(`/api/funder-matches/runs?org=${encodeURIComponent(org)}`, "POST");
