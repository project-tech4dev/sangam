import type { TraceStep } from "@/lib/useAgentChat";

type ActionRequest = { name?: string; args?: { paths?: unknown } };

/** The paths a paused select_source_files proposes; null when the interrupt is someone else's. */
export function proposedPaths(value: unknown): string[] | null {
  let request = value;
  if (typeof request === "string") {
    try {
      request = JSON.parse(request);
    } catch {
      return null;
    }
  }
  const actions = (request as { action_requests?: ActionRequest[] } | null)?.action_requests;
  const pick = actions?.find((a) => a?.name === "select_source_files");
  if (!pick) return null;
  const paths = pick.args?.paths;
  return Array.isArray(paths) ? paths.filter((p): p is string => typeof p === "string") : [];
}

/** Every workbook path the run's list_bucket_files calls printed, to offer beside the proposal. */
export function listedPaths(steps: TraceStep[]): string[] {
  const out = new Set<string>();
  for (const step of steps) {
    if (step.tool !== "list_bucket_files" || !step.result) continue;
    for (const line of step.result.split("\n")) {
      const match = /^- (staff-sources\/\S+?\.xlsx) ·/i.exec(line);
      if (match?.[1]) out.add(match[1]);
    }
  }
  return Array.from(out);
}
