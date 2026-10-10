import type { TraceStep } from "@/lib/useAgentChat";
import { fileLabel, host } from "./toolLabels";
import { pageOutcome, type PageOutcome } from "./words";

/** One organisation's progress, as the Working step shows it; `working` until its researcher reports. */
export type RowState = "working" | "paused" | "stopped" | "ready" | "notFound" | "wrong";

/** `site` is the host, whichever of title or where shows it. */
export type PageLine = { id: string; title: string; where: string; site: string; state: PageOutcome; text: string };

export type BoardRow = {
  id: string;
  name: string;
  state: RowState;
  /** Topics with an answer, and how many were asked for; null when not known yet. */
  found: number | null;
  total: number | null;
  pct: number;
  now: string;
  pages: PageLine[];
};

export type BoardEvent = { id: string; name: string | null; text: string };

export type Board = {
  rows: BoardRow[];
  ready: number;
  pagesRead: number;
  answers: number;
  pct: number;
  /** What is being read right now, for when steps can't be tied to one organisation. */
  now: string | null;
  events: BoardEvent[];
  /** Whether any step was tied to an organisation; without it rows show status only. */
  attributed: boolean;
};

const READING = ["read_page", "fetch_document", "read_document_pages"];
const NAMING = ["research_goals", "funder_dossier"];
const HELPERS = ["catalog-writer", "workbook-reader", "vault-reader"];

const a = (s: TraceStep): any => s.args ?? {};
const key = (name: string) => name.trim().toLowerCase();

/** The name the main agent put before the dash, e.g. "KABIL — find …". */
export function subjectOf(args: any): string {
  const description: string = args?.description ?? "";
  const head = (description.split(/\s[—–-]\s/, 1)[0] ?? "").trim();
  return head && head.length <= 60 ? head : description.slice(0, 60) || "An organisation";
}

function parse(result: string | null): any {
  if (result === null) return null;
  try {
    return JSON.parse(result);
  } catch {
    return {};
  }
}

function nameOf(step: TraceStep): string | null {
  if (NAMING.includes(step.tool)) return a(step).name ?? null;
  if (step.tool === "save_research") return a(step).findings?.entity_name ?? null;
  return null;
}

function pageOf(step: TraceStep): PageLine | null {
  const outcome = pageOutcome(step.result, step.running);
  if (step.tool === "read_document_pages") {
    // Reading a downloaded file is the same document again, so only a scan or a failure is a line of its own.
    if (outcome.state === "read" || outcome.state === "opening") return null;
    return { id: step.id, title: fileLabel(a(step).filename) || "A document", where: "", site: "", ...outcome };
  }
  const site = host(a(step).url);
  if (step.tool === "fetch_document") {
    return { id: step.id, title: fileLabel(a(step).filename) || "A document", where: site, site, ...outcome };
  }
  return { id: step.id, title: site || "A page", where: pathOf(a(step).url), site, ...outcome };
}

function pathOf(url?: string): string {
  try {
    const path = new URL(url ?? "").pathname.replace(/\/$/, "");
    return path.length > 40 ? `${path.slice(0, 40)}…` : path;
  } catch {
    return "";
  }
}

const isResearcher = (s: TraceStep) => s.tool === "task" && !HELPERS.includes(a(s).subagent_type);

export function boardOf(
  steps: TraceStep[],
  running: boolean,
  laneOwners: Record<string, string> = {},
  paused = false,
): Board {
  // One row per organisation, in the order they started; a re-run of the same name updates its row.
  const tasks = new Map<string, TraceStep>();
  for (const s of steps.filter(isResearcher)) tasks.set(key(subjectOf(s.args)), s);
  const rowKeyOfTask = new Map([...tasks].map(([k, s]) => [s.id, k]));

  // Which row a subagent's steps belong to: the task that started it, else the name it researched.
  const laneRow = new Map<string, string>();
  for (const [lane, taskId] of Object.entries(laneOwners)) {
    const k = rowKeyOfTask.get(taskId);
    if (k) laneRow.set(lane, k);
  }
  for (const s of steps) {
    const name = s.lane ? nameOf(s) : null;
    if (!s.lane || !name || laneRow.has(s.lane)) continue;
    const k = key(name);
    const match = [...tasks.keys()].find((t) => t === k || t.includes(k) || k.includes(t));
    if (match) laneRow.set(s.lane, match);
  }
  const rowOf = (s: TraceStep): string | null => (s.lane ? (laneRow.get(s.lane) ?? null) : null);

  const byRow = new Map<string, TraceStep[]>();
  for (const s of steps) {
    const k = rowOf(s);
    if (k) byRow.set(k, [...(byRow.get(k) ?? []), s]);
  }

  const rows: BoardRow[] = [...tasks].map(([k, task]) => {
    const own = byRow.get(k) ?? [];
    const summary = parse(task.result);
    const goals = own.find((s) => s.tool === "research_goals" && s.result);
    const total = goals ? (goals.result!.match(/^\w+ -> /gm) ?? []).length || null : null;
    const saved = own.filter((s) => s.tool === "save_research");
    const savedConcepts = new Set<string>(
      saved.flatMap((s) => (a(s).findings?.findings ?? []).map((f: any) => f?.concept)).filter(Boolean),
    );
    const found = Array.isArray(summary?.concepts_found)
      ? summary.concepts_found.length
      : savedConcepts.size > 0
        ? savedConcepts.size
        : null;
    const pages = own.filter((s) => READING.includes(s.tool)).map(pageOf).filter((p): p is PageLine => p !== null);

    let state: RowState = "ready";
    if (task.result === null) state = running ? "working" : paused ? "paused" : "stopped";
    else if (summary?.status === "not_found") state = "notFound";
    else if (summary?.status === "wrong_entity") state = "wrong";
    // The researcher's budget ran out (app/ingest/middleware.py): say so, or a thin row reads as a finished one.
    const atLimit = state === "ready" && /reading limit/i.test(summary?.stopped_reason ?? "");

    const reading = [...pages].reverse().find((p) => p.state === "opening");
    const done = pages.filter((p) => p.state !== "opening").length;
    const pct =
      state !== "working" && state !== "paused" && state !== "stopped"
        ? 100
        : saved.length > 0
          ? 90
          : goals
            ? Math.min(80, 15 + done * 7)
            : 5;
    const now =
      state === "stopped"
        ? "Stopped before it finished"
        : state === "paused"
          ? "Waiting for your answer"
        : state === "notFound"
          ? "Couldn't find it"
          : state === "wrong"
            ? "Found a different organisation"
            : atLimit
              ? "Stopped at the reading limit"
            : state === "ready"
              ? "Done"
              : saved.length > 0
                ? "Writing up"
                : reading
                  ? `Reading: ${reading.site || reading.title}`
                  : own.length === 0 || !goals
                    ? "Checking it's the right organisation"
                    : "Looking for sources";
    return { id: task.id, name: subjectOf(task.args), state, found, total, pct, now, pages };
  });

  const working = rows.some((r) => r.state === "working" || r.state === "paused");
  for (const r of rows) {
    if (r.state === "ready" && working) r.now = "Done — waiting for the others before you can review";
  }

  const reads = steps.filter((s) => READING.includes(s.tool) && s.tool !== "read_document_pages");
  const pagesRead = reads.filter((s) => pageOutcome(s.result, s.running).state === "read").length;
  const openNow = [...reads].reverse().find((s) => s.running);

  const nameFor = (s: TraceStep) => {
    const k = s.tool === "task" ? rowKeyOfTask.get(s.id) : rowOf(s);
    return k ? (rows.find((r) => key(r.name) === k)?.name ?? null) : null;
  };
  const events: BoardEvent[] = [];
  const byFinish = [...steps].sort((x, y) => (x.doneAt ?? 0) - (y.doneAt ?? 0));
  for (const s of byFinish) {
    if (s.result === null) continue;
    let text: string | null = null;
    if (READING.includes(s.tool)) {
      const p = pageOf(s);
      const what = s.tool === "read_page" ? p?.site || p?.title : `${p?.title}${p?.site ? ` from ${p.site}` : ""}`;
      if (p?.state === "read") text = `read ${what}`;
      else if (p?.state === "scanned") text = `opened ${what}: it is a scan, with no text to read`;
      else if (p) text = `couldn't open ${what}`;
    } else if (s.tool === "save_research") {
      const n = new Set((a(s).findings?.findings ?? []).map((f: any) => f?.concept)).size;
      text = `found ${n} answer${n === 1 ? "" : "s"}`;
    } else if (isResearcher(s)) {
      const row = rows.find((r) => r.id === s.id);
      text = row?.state === "ready" ? "is ready for your review ✓" : (row?.now.toLowerCase() ?? null);
    } else if (s.tool === "task" && a(s).subagent_type === "workbook-reader") {
      const n = parse(s.result)?.entities?.length ?? 0;
      text = `Found ${n} name${n === 1 ? "" : "s"} in your team's spreadsheets`;
    } else if (s.tool === "task" && a(s).subagent_type === "vault-reader") {
      const r = parse(s.result);
      const docs = r?.documents_read?.length ?? 0;
      const found = r?.concepts_found?.length ?? 0;
      text = `Read ${docs} of your organisation's document${docs === 1 ? "" : "s"}: ${found} answer${found === 1 ? "" : "s"}`;
    }
    const name = nameFor(s);
    if (text) events.push({ id: s.id, name, text: name ? text : text[0]!.toUpperCase() + text.slice(1) });
  }

  return {
    rows,
    ready: rows.filter((r) => r.state !== "working" && r.state !== "paused" && r.state !== "stopped").length,
    pagesRead,
    answers: rows.reduce((n, r) => n + (r.found ?? 0), 0),
    pct: rows.length ? Math.round(rows.reduce((n, r) => n + r.pct, 0) / rows.length) : 0,
    now: openNow ? `Reading: ${host(a(openNow).url) || fileLabel(a(openNow).filename)}` : null,
    events: events.slice(-4).reverse(),
    attributed: laneRow.size > 0,
  };
}
