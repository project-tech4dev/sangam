import { call } from "../../lib/rest";

export type FeedCall = {
  rfp_id: number;
  title: string;
  funder_id: number | null;
  funder_name: string | null;
  url: string | null;
  source_url: string | null;
  deadline: string | null;
  amount_min: number | null;
  amount_max: number | null;
  call_status: string;
  status: string;
  places: string[];
  themes: string[];
};

export type Feed = {
  org_id: number;
  org_name: string;
  can_act: boolean;
  domains: string[];
  last_pulled: string | null;
  items: FeedCall[];
};

export const getFeed = (org: string) => call<Feed>(`/api/rfps/feed?org=${encodeURIComponent(org)}`);
/** As the signed-in person; RLS lets only the org's members and admins, and staff, change it. */
export const setStatus = (rfpId: number, orgId: number, status: "flagged" | "saved" | "dismissed") =>
  call<{ status: string }>(`/api/rfps/${rfpId}/matches/${orgId}`, "PATCH", { status });
