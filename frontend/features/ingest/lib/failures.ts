import type { TraceStep } from "@/lib/useAgentChat";
import { humanizeTool, stepNote } from "./toolLabels";
import { plainReason } from "./words";

const ON_THE_BOARD = ["task", "read_page", "fetch_document", "read_document_pages"];

export type Failure = {
  id: string;
  label: string;
  detail: string;
  note: string;
  /** How many identical lines this one stands for. */
  count: number;
};

/**
 * A turn's refusals and failures, as lines worth reading.
 *
 * Grouped, because a model guessing five RFP URLs at one site produces five
 * identical 404s, and that is one fact rather than five lines. Subagents and
 * pages are excluded: the Working board shows both.
 */
export function failuresOf(steps: TraceStep[]): Failure[] {
  const grouped = new Map<string, Failure>();
  for (const step of steps) {
    if (ON_THE_BOARD.includes(step.tool)) continue;
    const raw = stepNote(step.result);
    if (raw === null) continue;
    const note = plainReason(raw);
    const { label, detail } = humanizeTool(step.tool);
    const key = `${label}|${detail(step.args)}|${note}`;
    const seen = grouped.get(key);
    if (seen) seen.count += 1;
    else grouped.set(key, { id: step.id, label, detail: detail(step.args), note, count: 1 });
  }
  return [...grouped.values()];
}
