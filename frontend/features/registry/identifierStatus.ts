import type { Identifier } from "@/lib/api";

/* One label per org_identifiers.status (0033). */
export const STATUS_LABELS: Record<string, string> = {
  applied: "Applied",
  provisional: "Provisional",
  registered: "Registered",
  expired: "Expired",
  suspended: "Suspended",
  cancelled: "Cancelled",
  surrendered: "Surrendered",
  not_available: "Not available",
  not_found: "Not found",
  check_blocked: "Check blocked",
};

/* A current numbered row first, then whatever row of that type there is. */
export function pickIdentifier(ids: Identifier[], idType: string): Identifier | undefined {
  const ofType = ids.filter((i) => i.id_type === idType);
  return ofType.find((i) => i.is_current && i.id_value) ?? ofType[0];
}

/* "Check blocked" never means valid, and a claimed status says so on its face. */
export function statusLabel(id: Identifier | undefined): string {
  if (!id) return "Not entered";
  const base = STATUS_LABELS[id.status] ?? id.status;
  return id.evidence === "claimed" ? `${base} (claimed)` : base;
}

export function statusTone(id: Identifier | undefined): "good" | "pending" | "bad" | "none" {
  if (!id) return "none";
  if (id.status === "registered" || id.status === "provisional") return "good";
  if (id.status === "applied" || id.status === "check_blocked") return "pending";
  return "bad";
}

export function isOnFile(id: Identifier | undefined): boolean {
  return !!id && !!id.id_value && id.is_current && (id.status === "registered" || id.status === "provisional");
}
