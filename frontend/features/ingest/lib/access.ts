import type { ImportTask } from "./composePrompt";

/** What the signed-in person may do in Import. The backend checks again; this only shapes the screen. */
export type ImportAccess = { staff: boolean; stewardOf: string[] };

type Me = { is_staff: boolean; memberships: { org_name: string; role: string }[] };

export function accessOf(me: Me): ImportAccess {
  return {
    staff: me.is_staff,
    stewardOf: me.memberships.filter((m) => m.role === "steward").map((m) => m.org_name),
  };
}

/** Staff: every task. A steward: funders and the NGOs it supports. Anyone else: funders. */
export function tasksFor(access: ImportAccess): ImportTask[] {
  if (access.staff) return ["funder", "ngo", "news"];
  return access.stewardOf.length ? ["funder", "ngo"] : ["funder"];
}
