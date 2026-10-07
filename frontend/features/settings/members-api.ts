import { authHeaders } from "@/lib/api/auth-headers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

export const ROLES = ["admin", "member", "steward"] as const;

export type OrgMember = { user_id: string; display_name: string | null; email: string; role: string };

export const selectClass = "h-8 rounded-full border border-neutral-300 bg-white px-2 text-sm";

export async function membersRequest(
  orgId: number,
  method = "GET",
  path = "",
  body?: object,
): Promise<{ members: OrgMember[] } | { error: string }> {
  try {
    const res = await fetch(`${API}/api/orgs/${orgId}/members${path}`, {
      method,
      headers: { ...(await authHeaders()), "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const payload = await res.json();
    if (!res.ok) return { error: typeof payload.detail === "string" ? payload.detail : "Something went wrong." };
    return { members: payload };
  } catch {
    return { error: "Could not reach Sangam. Try again." };
  }
}
