import type { ImportTask } from "./composePrompt";

/** What the signed-in person may do in Import. The backend checks again; this only shapes the screen. */
export type ImportAccess = { staff: boolean; stewardOf: string[]; orgs: { slug: string; name: string }[] };

/** One private file in an organisation's Doc Vault, which Import can read before the web. */
export type VaultFile = { id: number; title: string | null; doc_type: string | null; org: string; orgName: string };

type Me = { is_staff: boolean; memberships: { org_slug: string; org_name: string; role: string }[] };

export function accessOf(me: Me): ImportAccess {
  return {
    staff: me.is_staff,
    stewardOf: me.memberships.filter((m) => m.role === "steward").map((m) => m.org_name),
    orgs: me.memberships.map((m) => ({ slug: m.org_slug, name: m.org_name })),
  };
}

/** Staff: every task. A steward: funders and the NGOs it supports. Anyone else: funders. */
export function tasksFor(access: ImportAccess): ImportTask[] {
  if (access.staff) return ["funder", "ngo", "news"];
  return access.stewardOf.length ? ["funder", "ngo"] : ["funder"];
}
