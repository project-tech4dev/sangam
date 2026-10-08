import type { TraceStep } from "@/lib/useAgentChat";

type ActionRequest = { name?: string; args?: Record<string, unknown> };

/** The tool call a HumanInTheLoopMiddleware interrupt is paused on, or null. */
export function pausedAction(value: unknown): ActionRequest | null {
  let request = value;
  if (typeof request === "string") {
    try {
      request = JSON.parse(request);
    } catch {
      return null;
    }
  }
  const actions = (request as { action_requests?: ActionRequest[] } | null)?.action_requests;
  return actions?.find((a) => a?.name === "select_source_files" || a?.name === "list_bucket_files") ?? null;
}

/** The paths a paused select_source_files proposes; null when the interrupt is not one. */
export function proposedPaths(value: unknown): string[] | null {
  const pick = pausedAction(value);
  if (pick?.name !== "select_source_files") return null;
  const paths = pick.args?.paths;
  return Array.isArray(paths) ? paths.filter((p): p is string => typeof p === "string") : [];
}

/** The bucket a paused list_bucket_files proposes; null when the interrupt is not one. */
export function proposedBucket(value: unknown): { bucket: string; prefix: string } | null {
  const pick = pausedAction(value);
  if (pick?.name !== "list_bucket_files") return null;
  const { bucket, prefix } = pick.args ?? {};
  return { bucket: typeof bucket === "string" ? bucket : "", prefix: typeof prefix === "string" ? prefix : "" };
}

function resultLines(steps: TraceStep[], tool: string): string[] {
  return steps.filter((s) => s.tool === tool && s.result).flatMap((s) => (s.result ?? "").split("\n"));
}

/** Every workbook path the run's list_bucket_files calls printed, to offer beside the proposal. */
export function listedPaths(steps: TraceStep[]): string[] {
  const out = new Set<string>();
  for (const line of resultLines(steps, "list_bucket_files")) {
    const match = /^- ([a-z0-9][a-z0-9._-]*\/\S+?\.xlsx) ·/i.exec(line);
    if (match?.[1]) out.add(match[1]);
  }
  return Array.from(out);
}

/** Every bucket list_storage_buckets printed, e.g. "- staff-sources (private) — …". */
export function listedBuckets(steps: TraceStep[]): string[] {
  const out = new Set<string>();
  for (const line of resultLines(steps, "list_storage_buckets")) {
    const match = /^- ([a-z0-9][a-z0-9._-]*) \((?:public|private)\)/i.exec(line);
    if (match?.[1]) out.add(match[1]);
  }
  return Array.from(out);
}
