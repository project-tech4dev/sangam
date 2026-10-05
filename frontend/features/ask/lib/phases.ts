import type { TraceStep, Turn } from "./useSangamChat";

/*
 * The high-level task, derived from the tool sequence.
 *
 * The agent has no plan artifact: it runs six tools and writes no todo list, so there is
 * nothing to read a "task" out of. What it does have is a shape — discover the schema,
 * check how values are stored, then query — and that shape is what a reader wants from
 * the rail while the per-step detail scrolls past in the chat.
 *
 * Only phases that actually happened are rendered. A pending phase the agent may never
 * reach would be a guess dressed as a plan.
 */

type PhaseSpec = { key: string; title: string };

const BY_TOOL: Record<string, PhaseSpec> = {
  db_list_tables: { key: "discover", title: "Finding the data" },
  db_describe_table: { key: "schema", title: "Reading the table structure" },
  db_profile_column: { key: "values", title: "Checking how values are stored" },
  db_query: { key: "query", title: "Querying" },
  search_graph: { key: "graph", title: "Reading the knowledge graph" },
  fetch_url: { key: "web", title: "Reading a web page" },
};

export type Phase = {
  id: string;
  title: string;
  steps: number;
  note: string;
  state: "done" | "active";
};

/** `args` arrives as a partial JSON string mid-stream, so every read tolerates a non-object. */
function arg(args: unknown, key: string): string {
  if (!args || typeof args !== "object") return "";
  const value = (args as Record<string, unknown>)[key];
  return typeof value === "string" ? value : "";
}

function noteFor(tool: string, steps: TraceStep[]): string {
  const last = steps[steps.length - 1]!;
  switch (tool) {
    case "db_describe_table":
      return [...new Set(steps.flatMap((s) => arg(s.args, "tables").split(",")))]
        .map((t) => t.trim())
        .filter(Boolean)
        .join(", ");
    case "db_profile_column":
      return [arg(last.args, "table"), arg(last.args, "column")].filter(Boolean).join(".");
    case "db_query":
      // The model's own one-line statement of what it is trying to learn.
      return arg(last.args, "purpose");
    case "search_graph":
      return arg(last.args, "query");
    case "fetch_url":
      return arg(last.args, "url");
    default:
      return "";
  }
}

/** One phase per run of consecutive steps on the same tool group, in the order they ran. */
export function phasesFor(turn: Turn | null): Phase[] {
  if (!turn) return [];
  const runs: { spec: PhaseSpec; tool: string; steps: TraceStep[] }[] = [];
  for (const step of turn.steps) {
    const spec = BY_TOOL[step.tool];
    if (!spec) continue;
    const open = runs[runs.length - 1];
    if (open && open.spec.key === spec.key) open.steps.push(step);
    else runs.push({ spec, tool: step.tool, steps: [step] });
  }

  return runs.map((run, i) => ({
    id: `${run.spec.key}-${i}`,
    title: run.spec.title,
    steps: run.steps.length,
    note: noteFor(run.tool, run.steps),
    state: run.steps.some((s) => s.running) ? "active" : "done",
  }));
}
