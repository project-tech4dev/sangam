import { authHeaders } from "@/lib/api/auth-headers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

export type BaselineSource = {
  url: string;
  kind: string | null;
  snapshot_id: number;
  read_on: string;
  archived: boolean;
  facts: number;
};

export type Baseline = { slug: string; sources: BaselineSource[]; unrecorded: number };

export type Evidence = { verdict: "intact" | "broken" | "unanchored"; sentence: string };

export type SourceCheck = {
  url: string;
  status: string;
  detail: string | null;
  findings_intact: number;
  findings_broken: number;
  findings_unanchored: number;
  judge: { meaningful?: boolean; reason?: string; confidence?: string } | null;
  removed_text: string[];
  added_text: string[];
  evidence: Evidence[] | null;
  baseline_snapshot_id: number | null;
  new_snapshot_id: number | null;
  baseline_seen_at: string | null;
  baseline_hash?: string | null;
  today_hash?: string | null;
};

export type CheckRun = {
  run_id: string;
  slug: string;
  depth: "free" | "full";
  decision: string | null;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  refresh_row_id: number | null;
  refresh_summary: string | null;
  requested_by: string | null;
  sources: number;
};

export type CheckRunDetail = CheckRun & { checks: SourceCheck[] };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { ...(await authHeaders()), ...(init?.body ? { "Content-Type": "application/json" } : {}) },
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(body?.detail ?? `${init?.method ?? "GET"} ${path} failed: ${res.status}`);
  return body as T;
}

const research = (slug: string) => `/api/ingest/research/${encodeURIComponent(slug)}`;

export const fetchBaseline = (slug: string) => call<Baseline>(`${research(slug)}/baseline`);
export const fetchChecks = (slug: string) => call<CheckRun[]>(`${research(slug)}/checks`);
export const fetchCheck = (runId: string) => call<CheckRunDetail>(`/api/ingest/checks/${runId}`);

/** Runs the check and waits for it: about a minute for a few sources, longer with the update. */
export const runCheck = (slug: string, depth: "free" | "full", refresh = false) =>
  call<CheckRunDetail>(`${research(slug)}/checks`, { method: "POST", body: JSON.stringify({ depth, refresh }) });

/** One source's result in words, and the tag colour it shows in. */
export function statusOf(status: string): { label: string; tag: string } {
  switch (status) {
    case "unchanged":
      return { label: "Unchanged", tag: "tag-neutral" };
    case "minor":
      return { label: "Minor edit", tag: "tag-neutral" };
    case "differs":
      return { label: "Text differs", tag: "tag-accent" };
    case "changed":
      return { label: "Changed", tag: "tag-accent" };
    case "dead":
      return { label: "Page gone", tag: "tag-accent" };
    case "new":
      return { label: "New source", tag: "tag-accent-2" };
    case "unverified":
      return { label: "Couldn't open", tag: "tag-outline" };
    default:
      return { label: status, tag: "tag-outline" };
  }
}

export type Verdict = { title: string; text: string; next: "none" | "judge" | "update" | "research" };

/** What the decision means for the person, and the one thing to do next. */
export function verdictOf(run: CheckRun): Verdict {
  if (run.error) return { title: "The check failed", text: run.error, next: "none" };
  switch (run.decision) {
    case "nothing to do":
      return { title: "Nothing to do", text: "Everything Sangam holds from these sources is still on them.", next: "none" };
    case "needs the judge":
      return {
        title: "Some text changed, every fact is still there",
        text: "A page's wording changed but each fact's sentence is still on it. The judge can say whether the change matters.",
        next: "judge",
      };
    case "refresh":
      return run.refresh_row_id
        ? { title: "Update saved for review", text: run.refresh_summary ?? "", next: "none" }
        : { title: "A change found", text: "Update only what changed, then review it before it reaches the profile.", next: "update" };
    case "full pull":
      return { title: "Most sources changed", text: "This looks like a new website. Research the organisation again.", next: "research" };
    default:
      return { title: "Checking…", text: "", next: "none" };
  }
}

export type Step = { name: string; state: "done" | "skipped" | "failed" | "flag"; text: string };

const short = (hash: string | null | undefined) => (hash ? hash.slice(0, 12) : "—");
const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

/** The five stages one source went through, in words, from what the check saved. */
export function stepsOf(c: SourceCheck, depth: "free" | "full", facts: number): Step[] {
  const read = c.status !== "unverified" && c.status !== "dead";
  const same = c.status === "unchanged";
  const steps: Step[] = [];
  steps.push(
    c.status === "unverified"
      ? { name: "Fetch today's version", state: "failed", text: `Couldn't open it (${c.detail ?? "no answer"}). Not counted as a change.` }
      : c.status === "dead"
        ? { name: "Fetch today's version", state: "flag", text: `The page is gone (${c.detail ?? "404"}).` }
        : c.status === "new"
          ? { name: "Fetch today's version", state: "flag", text: "A source no research has read, found on the organisation's site." }
          : { name: "Fetch today's version", state: "done", text: "Opened and read." },
  );
  steps.push(
    !read || c.status === "new"
      ? { name: "Compare fingerprints", state: "skipped", text: "Nothing to compare." }
      : same
        ? { name: "Compare fingerprints", state: "done", text: `Same text: kept copy ${short(c.baseline_hash)} = today ${short(c.today_hash)}.` }
        : { name: "Compare fingerprints", state: "flag", text: `Different: kept copy ${short(c.baseline_hash)} → today ${short(c.today_hash)}.` },
  );
  const changedLines = c.removed_text.length + c.added_text.length;
  steps.push(
    !read || c.status === "new"
      ? { name: "Compare the text", state: "skipped", text: "Nothing to compare." }
      : same
        ? { name: "Compare the text", state: "skipped", text: "Not needed: the fingerprints match, so the text is identical." }
        : c.status === "minor" && changedLines === 0
          ? { name: "Compare the text", state: "done", text: "Only the order or spacing changed." }
          : changedLines === 0
            ? { name: "Compare the text", state: "flag", text: c.detail ?? "Couldn't compare: no kept copy to read." }
            : { name: "Compare the text", state: "flag",
                text: `${plural(c.removed_text.length, "paragraph")} removed, ${plural(c.added_text.length, "paragraph")} added.` },
  );
  const checked = c.findings_intact + c.findings_broken + c.findings_unanchored;
  steps.push(
    c.status === "dead"
      ? { name: "Check each fact is still there", state: "flag", text: `${plural(facts, "fact")} cite a page that is gone.` }
      : !read || c.status === "new"
        ? { name: "Check each fact is still there", state: "skipped", text: "Nothing to check." }
        : same
          ? { name: "Check each fact is still there", state: "skipped", text: `Not needed: the text is identical, so all ${plural(facts, "fact")} still hold.` }
          : checked === 0
            ? { name: "Check each fact is still there", state: "skipped", text: "No fact quotes this source." }
            : { name: "Check each fact is still there", state: c.findings_broken ? "flag" : "done",
                text: `${c.findings_intact} still there · ${c.findings_broken} gone or changed · ${c.findings_unanchored} can't tell.` },
  );
  steps.push(
    c.judge
      ? { name: "Ask the judge (Haiku)", state: c.judge.meaningful ? "flag" : "done",
          text: `${c.judge.meaningful ? "Matters" : "Doesn't matter"}${c.judge.reason ? `: ${c.judge.reason}` : "."}` }
      : depth === "free"
        ? { name: "Ask the judge (Haiku)", state: "skipped", text: same || !read ? "Not needed." : "Not run: a free check never calls the AI." }
        : { name: "Ask the judge (Haiku)", state: "skipped",
            text: c.findings_broken ? "Not needed: a fact is already gone, so it changed." : "Not needed." },
  );
  return steps;
}

/** The whole check in one line: how many sources reached each stage. */
export function summaryOf(run: CheckRunDetail): string {
  const n = run.checks.length;
  const opened = run.checks.filter((c) => c.status !== "unverified" && c.status !== "dead").length;
  const same = run.checks.filter((c) => c.status === "unchanged").length;
  const compared = run.checks.filter((c) => c.removed_text.length + c.added_text.length > 0).length;
  const judged = run.checks.filter((c) => c.judge).length;
  return `${plural(n, "source")} · ${opened} opened · ${same} same fingerprint · ${compared} text compared · ${judged} judged`;
}
