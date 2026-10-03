import type { TraceStep } from "@/lib/useAgentChat";
import { humanizeTool, stepNote } from "./toolLabels";

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
 * identical 404s, and that is one fact rather than five lines. `task` is
 * excluded: SubagentBoard already reports a subagent that stopped.
 */
export function failuresOf(steps: TraceStep[]): Failure[] {
  const grouped = new Map<string, Failure>();
  for (const step of steps) {
    if (step.tool === "task") continue;
    const note = stepNote(step.result);
    if (note === null) continue;
    const { label, detail } = humanizeTool(step.tool);
    const key = `${label}|${detail(step.args)}|${note}`;
    const seen = grouped.get(key);
    if (seen) seen.count += 1;
    else grouped.set(key, { id: step.id, label, detail: detail(step.args), note, count: 1 });
  }
  return [...grouped.values()];
}
