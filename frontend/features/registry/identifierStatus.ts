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

/* The writer's precedence; an unranked row is a person's entry and ranks with the registry. */
const SOURCE_RANK: Record<string, number> = {
  registry: 7, manual_check: 7, org_document: 6, funder: 5,
  staff_dataset: 4, prior_research: 3, aggregator: 2, seed: 1,
};

/* Current first, then the stronger source (an aggregator never hides the org's own "applied"), then numbered. */
export function pickIdentifier(ids: Identifier[], idType: string): Identifier | undefined {
  const rank = (i: Identifier) => (i.source_type ? SOURCE_RANK[i.source_type] ?? 0 : 7);
  return ids
    .filter((i) => i.id_type === idType)
    .sort((a, b) => Number(b.is_current) - Number(a.is_current) || rank(b) - rank(a)
      || Number(!!b.id_value) - Number(!!a.id_value))[0];
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
