import type { TraceStep } from "@/lib/useAgentChat";
import type { CoverageCell, CoverageConcept, ResearchCoverage } from "./types";

/** Every organisation a run researched or saved, by slug, in the order it first appeared. */
export function slugsOf(steps: TraceStep[]): string[] {
  const out: string[] = [];
  const add = (slug: unknown) => {
    if (typeof slug === "string" && slug && !out.includes(slug)) out.push(slug);
  };
  for (const s of steps) {
    if (s.tool === "task" && s.result) {
      try {
        add(JSON.parse(s.result)?.slug);
      } catch {
        // A helper's prose result names no slug.
      }
    }
    if (s.tool === "promote_research") add((s.args as { slug?: unknown } | undefined)?.slug);
  }
  return out;
}

export const isSaved = (c: ResearchCoverage) => c.stage === "saved" && c.entity !== null;

/** The bar for one topic: what Sangam already had and kept, what changed, what is new. */
export function topicBar(c: CoverageConcept): { kept: number; updated: number; added: number } {
  const updated = c.updated;
  const added = c.added;
  const kept = Math.max(0, (c.before ?? 0) - updated);
  return { kept, updated, added };
}

const REASON: Record<Exclude<CoverageCell["status"], "found">, string> = {
  not_written: "Found, nowhere to save it",
  blocked: "Couldn't read",
  not_stated: "Not on their website",
  not_attempted: "Not looked for",
};
const ORDER: Exclude<CoverageCell["status"], "found">[] = ["not_written", "blocked", "not_stated", "not_attempted"];

/** Why a topic has nothing in Sangam, or null when it has something. */
export function emptyReason(c: CoverageConcept): string | null {
  const { kept, updated, added } = topicBar(c);
  if (kept + updated + added > 0 || (c.after ?? 0) > 0) return null;
  const why = ORDER.find((s) => c.cells.some((cell) => cell.status === s));
  if (why) return REASON[why];
  return wasFound(c) ? "Found, nowhere to save it" : "Not found";
}

export const wasFound = (c: CoverageConcept) => c.cells.some((cell) => cell.status === "found");

/** Share of topics with anything in Sangam, before and after the save. */
export function completeness(c: ResearchCoverage): { before: number; after: number } {
  const n = c.concepts.length;
  if (n === 0) return { before: 0, after: 0 };
  const before = c.concepts.filter((t) => (t.before ?? 0) > 0).length;
  const after = c.concepts.filter((t) => (t.before ?? 0) > 0 || (t.after ?? 0) > 0 || t.added > 0).length;
  return { before: before / n, after: after / n };
}

export const addedOf = (c: ResearchCoverage) => c.concepts.reduce((n, t) => n + t.added, 0);

/** The research's own words for why a topic has no answer, when it gave any. */
export function gapDetail(c: CoverageConcept): string | null {
  return c.cells.find((cell) => cell.status !== "found" && cell.detail)?.detail ?? null;
}

/** What saving did to one topic, or why it is still empty. */
export function topicLine(c: CoverageConcept): string {
  const why = emptyReason(c);
  if (why) return why;
  const said = [c.added && `+${c.added} added`, c.updated && `${c.updated} updated`].filter(Boolean).join(", ");
  return said || "No change";
}

/** The saved organisation's profile page, or null before it has one. */
export function profileOf(c: ResearchCoverage): string | null {
  const id = c.entity?.id;
  if (!isSaved(c) || id === null || id === undefined) return null;
  return c.entity?.kind === "funder" ? `/registry/funders/${id}` : `/registry/${id}`;
}
