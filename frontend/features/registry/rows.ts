/* What a Registry row says, and what each filter matches: presentation over GET /api/registry. */

import type { RegistryRow } from "@/lib/api";
import { dayMonth, formatInr, funderTypeLabel, MONTHS } from "@/lib/format";

export const NORTH_EAST = [
  "Arunachal Pradesh", "Assam", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Sikkim", "Tripura",
];

export function kindLine(r: RegistryRow): string {
  if (r.kind === "org") {
    if (!r.place) return "CSO";
    const more = r.states.length - 1;
    return `CSO · ${r.place}${more > 0 ? ` and ${more} more ${more === 1 ? "state" : "states"}` : ""}`;
  }
  const type = funderTypeLabel(r.funder_type);
  if (r.states.length === 0) return type;
  if (r.states.length <= 3) return `${type} · ${r.states.join(", ")}`;
  const ne = r.states.find((s) => NORTH_EAST.includes(s));
  return `${type} · ${r.states.length} states${ne ? `, including ${ne}` : ""}`;
}

/* One line of what is known: activity, money, research — each part only when the data holds it. */
export function signal(r: RegistryRow): string {
  const parts: string[] = [];
  if (r.kind === "funder") {
    if (r.csr_prescribed != null) parts.push(`${formatInr(r.csr_prescribed)} prescribed CSR, ${r.csr_year}`);
    if (r.open_call) parts.push("open call now");
    if (r.intake_mode === "invitation_only") parts.push("invites partners");
    if (r.partners > 0) parts.push(`${r.partners} ${r.partners === 1 ? "partner" : "partners"}`);
  } else if (r.partners > 0) {
    parts.push(`${r.partners} ${r.partners === 1 ? "funder" : "funders"} named`);
  }
  if (r.social > 0) {
    const since = r.posts_since ? ` since ${MONTHS[Number(r.posts_since.slice(5, 7)) - 1]}` : "";
    parts.push(`${r.social} ${r.social === 1 ? "post" : "posts"}${since}`);
  }
  if (r.press > 0) parts.push(`${r.press} public ${r.press === 1 ? "story" : "stories"}`);
  if (r.research_runs > 0) {
    parts.push(r.researched_on ? `researched ${dayMonth(r.researched_on)}` : "researched");
    if (r.press + r.social === 0 && r.kind === "org") parts.push("no stories yet");
  } else {
    parts.push("Not researched yet");
  }
  const line = parts.join(" · ");
  return line.charAt(0).toUpperCase() + line.slice(1);
}

export type Filters = {
  kind: "all" | "org" | "funder"; theme: string; population: string; sdg: string; where: string;
  reg: string; ftype: string; approach: string; q: string;
};

export const DEFAULTS: Omit<Filters, "kind"> = {
  theme: "all", population: "all", sdg: "all", where: "any", reg: "any", ftype: "all", approach: "any", q: "",
};

function worksIn(r: RegistryRow, where: string): boolean {
  if (where === "any") return true;
  if (where === "ne") return r.states.some((s) => NORTH_EAST.includes(s));
  if (where === "out") return r.states.some((s) => !NORTH_EAST.includes(s));
  return r.states.includes(where);
}

export function matches(r: RegistryRow, f: Filters): boolean {
  if (f.kind !== "all" && r.kind !== f.kind) return false;
  if (f.theme !== "all" && !r.themes.some((t) => t.domain === f.theme)) return false;
  if (f.population !== "all" && !r.populations.includes(f.population)) return false;
  if (f.sdg !== "all" && !r.sdgs.includes(f.sdg)) return false;
  if (!worksIn(r, f.where)) return false;
  if (f.kind === "org" && f.reg !== "any") {
    if (f.reg === "csr1" && !r.csr1) return false;
    if (f.reg === "12a80g" && !r.has_12a_80g) return false;
    if (f.reg === "fcra" && !r.fcra) return false;
  }
  if (f.kind === "funder") {
    if (f.ftype !== "all" && r.funder_type !== f.ftype) return false;
    if (f.approach === "open" && !r.open_call) return false;
    if (f.approach === "invites" && r.intake_mode !== "invitation_only") return false;
  }
  const q = f.q.trim().toLowerCase();
  return !q || r.search.includes(q) || r.name.toLowerCase().includes(q);
}

/* Each value present in the data, most common first. */
export function present(values: string[]): string[] {
  const n = new Map<string, number>();
  for (const v of values) n.set(v, (n.get(v) ?? 0) + 1);
  return [...n.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([v]) => v);
}
