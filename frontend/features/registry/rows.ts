/* What a Registry row says: presentation over GET /api/registry. Filtering happens on the server. */

import type { RegistryRow } from "@/lib/api";
import { dayMonth, formatInr, funderTypeLabel, MONTHS } from "@/lib/format";

export { DEFAULTS, type Filters } from "./filtersUrl";

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
