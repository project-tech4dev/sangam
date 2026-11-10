import type { ImportTask } from "./composePrompt";

/** What the signed-in person may do in Import. The backend checks again; this only shapes the screen. */
export type ImportAccess = { staff: boolean; stewardOf: string[]; orgs: { slug: string; name: string }[] };

/** One private file in an organisation's Doc Vault, which Import can read before the web. */
export type VaultFile = {
  id: number;
  title: string | null;
  doc_type: string | null;
  org: string;
  orgId: number;
  orgName: string;
};

export type Me = { is_staff: boolean; memberships: { org_slug: string; org_name: string; role: string }[] };

export function accessOf(me: Me): ImportAccess {
  return {
    staff: me.is_staff,
    stewardOf: me.memberships.filter((m) => m.role === "steward").map((m) => m.org_name),
    orgs: me.memberships.map((m) => ({ slug: m.org_slug, name: m.org_name })),
  };
}

/** Scout is for Sangam staff and the stewards of an org; the backend refuses everyone else. */
export function canUseScout(me: Me): boolean {
  return me.is_staff || me.memberships.some((m) => m.role === "steward");
}

/** Staff: every task. A steward: funders and the NGOs it supports. Anyone else: none. */
export function tasksFor(access: ImportAccess): ImportTask[] {
  if (access.staff) return ["funder", "ngo", "news", "calls"];
  return access.stewardOf.length ? ["funder", "ngo"] : [];
}
