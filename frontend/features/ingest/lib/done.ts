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
  return why ? REASON[why] : "Not found";
}

export type Square = "new" | "updated" | "kept" | "empty";

/** One topic as a square in the run matrix. */
export function squareOf(c: CoverageConcept): Square {
  const { kept, updated, added } = topicBar(c);
  if (added > 0) return "new";
  if (updated > 0) return "updated";
  return kept > 0 || (c.after ?? 0) > 0 ? "kept" : "empty";
}

/** Facts before and after across the saved organisations; null when none has both. */
export function runTotal(all: ResearchCoverage[]): { before: number; after: number } | null {
  const counted = all.filter((c) => isSaved(c) && c.facts_before !== null && c.facts_after !== null);
  if (counted.length === 0) return null;
  return {
    before: counted.reduce((n, c) => n + (c.facts_before ?? 0), 0),
    after: counted.reduce((n, c) => n + (c.facts_after ?? 0), 0),
  };
}

/** One line on what saving did, or why it didn't happen. */
export function summaryLine(c: ResearchCoverage): string {
  if (!isSaved(c)) return "Not saved. What Sangam found is kept in Researched recently.";
  const added = c.concepts.reduce((n, t) => n + t.added, 0);
  const updated = c.concepts.reduce((n, t) => n + t.updated, 0);
  if (added + updated === 0) return "Saved. Sangam already had everything found.";
  return `Saved: ${[added && `${added} new`, updated && `${updated} updated`].filter(Boolean).join(", ")}.`;
}

/** The saved organisation's profile page, or null before it has one. */
export function profileOf(c: ResearchCoverage): string | null {
  const id = c.entity?.id;
  if (!isSaved(c) || id === null || id === undefined) return null;
  return c.entity?.kind === "funder" ? `/registry/funders/${id}` : `/registry/${id}`;
}
