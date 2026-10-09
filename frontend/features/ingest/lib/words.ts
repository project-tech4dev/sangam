import { stepNote } from "./toolLabels";
import type { ResearchRecord } from "./types";

/** Staff never see engine words; every Import label for one comes from here. */
export const KIND_LABEL: Record<string, string> = { funder: "Funder", org: "NGO" };

export const kindLabel = (kind: string) => KIND_LABEL[kind] ?? "Organisation";

type Shelf = { label: string; tag: string };

/** What happened to one research row, as staff read it. */
export function researchState(r: ResearchRecord): Shelf {
  if (r.status === "not_found") return { label: "Couldn't find it", tag: "tag-outline" };
  if (r.status === "wrong_entity") return { label: "Found a different organisation", tag: "tag-outline" };
  if (r.saved_at || r.resolved_funder_id || r.resolved_org_id) return { label: "Saved", tag: "tag-accent-2" };
  return { label: "Not saved", tag: "tag-neutral" };
}

/** The profile a saved row became, or null when it has none yet. */
export function profileHref(r: ResearchRecord): string | null {
  if (r.resolved_funder_id) return `/registry/funders/${r.resolved_funder_id}`;
  if (r.resolved_org_id) return `/registry/${r.resolved_org_id}`;
  return null;
}

export type PageOutcome = "opening" | "read" | "blocked" | "scanned";

/** How one page or document went, in words with no status codes in them. */
export function pageOutcome(result: string | null, running: boolean): { state: PageOutcome; text: string } {
  if (result === null) return running ? { state: "opening", text: "Opening…" } : { state: "blocked", text: "Couldn't open" };
  if (/most likely scanned/i.test(result)) return { state: "scanned", text: "Scanned — no text to read" };
  const note = stepNote(result);
  if (note === null) return { state: "read", text: "Read" };
  const why = /^HTTP \d{3}/.test(note) ? plainReason(note) : null;
  return { state: "blocked", text: why ? `Couldn't open — ${why}` : "Couldn't open" };
}

/** A failure's reason with any status code put into words. */
export function plainReason(note: string): string {
  if (/\b(401|403|429|451)\b/.test(note)) return "the site said no";
  if (/\b(404|410)\b/.test(note)) return "the page isn't there";
  if (/\bHTTP 5\d\d\b/.test(note)) return "the site had a problem";
  return note.replace(/\bHTTP \d{3}\s*/g, "").trim() || "it didn't work";
}
