import type { TraceStep } from "@/lib/useAgentChat";

type ActionRequest = { name?: string; args?: Record<string, unknown> };

/** Where one run reads from, as choose_sources takes it. */
export type SourcesChoice = {
  web: boolean;
  library: boolean;
  vault_org: number | null;
  vault_docs: number[];
  staff_paths: string[];
};

/** Nothing ticked: the person chooses every source. */
export const EMPTY_SOURCES: SourcesChoice = { web: false, library: false, vault_org: null, vault_docs: [], staff_paths: [] };

export const nothingChosen = (c: SourcesChoice) => !c.web && !c.library && c.vault_docs.length === 0 && c.staff_paths.length === 0;

/** The tool call a HumanInTheLoopMiddleware interrupt is paused on, or null. */
function pausedAction(value: unknown, name: string): ActionRequest | null {
  let request = value;
  if (typeof request === "string") {
    try {
      request = JSON.parse(request);
    } catch {
      return null;
    }
  }
  const actions = (request as { action_requests?: ActionRequest[] } | null)?.action_requests;
  return actions?.find((a) => a?.name === name) ?? null;
}

const ids = (v: unknown) => (Array.isArray(v) ? v.map(Number).filter(Number.isInteger) : []);

/** What a paused choose_sources proposes; null when the interrupt is not one. */
export function proposedSources(value: unknown): SourcesChoice | null {
  const action = pausedAction(value, "choose_sources");
  if (!action) return null;
  const a = action.args ?? {};
  return {
    web: a.web !== false,
    library: a.library !== false,
    vault_org: typeof a.vault_org === "number" ? a.vault_org : null,
    vault_docs: ids(a.vault_docs),
    staff_paths: Array.isArray(a.staff_paths) ? a.staff_paths.filter((p): p is string => typeof p === "string") : [],
  };
}

/** The person's answer: always an edit, so the run reads exactly what was ticked. */
export function sourcesDecision(choice: SourcesChoice) {
  return { type: "edit" as const, edited_action: { name: "choose_sources", args: choice } };
}

/** "Public websites · Sangam's library · …" from the run's answered choose_sources, or null before it. */
export function readingFrom(steps: TraceStep[]): string | null {
  const step = [...steps].reverse().find((s) => s.tool === "choose_sources" && s.result && !/REFUSED|failed/.test(s.result));
  if (!step?.result) return null;
  const said = (label: string) => new RegExp(`- ${label}: yes`).test(step.result ?? "");
  const vault = /Doc Vault of org \d+: documents ([\d, ]+)/.exec(step.result)?.[1]?.split(",").length ?? 0;
  const staff = (step.result.match(/- team spreadsheet .+ → document \d+/g) ?? []).length;
  const parts = [
    said("public websites") && "Public websites",
    said("Sangam's library") && "Sangam's library",
    vault > 0 && `Doc Vault (${vault})`,
    staff > 0 && `Team spreadsheets (${staff})`,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}
