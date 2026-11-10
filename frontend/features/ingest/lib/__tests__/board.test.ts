import { describe, expect, it } from "vitest";
import type { TraceStep } from "@/lib/useAgentChat";
import { boardOf, subjectOf } from "../board";

let n = 0;
const step = (tool: string, args: unknown, result: string | null, extra: Partial<TraceStep> = {}): TraceStep => ({
  id: `s${++n}`, tool, args, result, running: result === null, ...extra,
});
const researcher = (description: string, result: string | null, extra: Partial<TraceStep> = {}) =>
  step("task", { description, subagent_type: "entity-researcher" }, result, extra);

describe("subjectOf", () => {
  it("takes the name before the dash, else the start of the description", () => {
    expect(subjectOf({ description: "KABIL — find their funding" })).toBe("KABIL");
    expect(subjectOf({ description: "Tata Trusts - CSR policy" })).toBe("Tata Trusts");
    expect(subjectOf({ description: "x".repeat(80) })).toBe("x".repeat(60));
    expect(subjectOf({})).toBe("An organisation");
  });
});

describe("boardOf", () => {
  it("tracks two organisations by lane and by name, with progress and events", () => {
    const kabil = researcher("KABIL — find funding", null, { running: true });
    const pratham = researcher("Pratham — legal standing", JSON.stringify({ status: "ready", concepts_found: ["a", "b", "c"] }), {
      doneAt: 3,
    });
    const steps = [
      kabil,
      step("research_goals", { name: "KABIL" }, "revenue -> x\nboard -> y\n", { lane: "A", doneAt: 0.5 }),
      step("read_page", { url: "https://www.kabil.org/about/" }, "Lots of text", { lane: "A", doneAt: 1 }),
      step("read_page", { url: "https://kabil.org/team" }, null, { lane: "A" }),
      pratham,
      step("research_goals", { name: "Pratham" }, "a -> b", { lane: "B", doneAt: 1.5 }),
      step("save_research", { findings: { entity_name: "Pratham", findings: [{ concept: "a" }, { concept: "a" }] } }, "ok", {
        lane: "B", doneAt: 2,
      }),
      step("task", { description: "Read the sheet", subagent_type: "workbook-reader" }, JSON.stringify({ entities: [1] }), {
        doneAt: 4,
      }),
    ];
    const board = boardOf(steps, true, { A: kabil.id });

    expect(board.rows.map(({ name, state, found, total, pct, now }) => ({ name, state, found, total, pct, now }))).toEqual([
      { name: "KABIL", state: "working", found: null, total: 2, pct: 22, now: "Reading: kabil.org" },
      { name: "Pratham", state: "ready", found: 3, total: 1, pct: 100, now: "Done — waiting for the others before you can review" },
    ]);
    expect(board.rows[0]!.pages.map((p) => [p.title, p.where, p.state])).toEqual([
      ["kabil.org", "/about", "read"],
      ["kabil.org", "/team", "opening"],
    ]);
    expect(board).toMatchObject({ ready: 1, pagesRead: 1, answers: 3, pct: 61, now: "Reading: kabil.org", attributed: true });
    expect(board.events.map((e) => [e.name, e.text])).toEqual([
      [null, "Found 1 name in your team's spreadsheets"],
      ["Pratham", "is ready for your review ✓"],
      ["Pratham", "found 1 answer"],
      ["KABIL", "read kabil.org"],
    ]);
  });

  it("names each finished or stopped state", () => {
    const rows = (steps: TraceStep[], running = false, paused = false) =>
      boardOf(steps, running, {}, paused).rows.map((r) => [r.state, r.now, r.pct]);

    expect(rows([researcher("A — x", null)])).toEqual([["stopped", "Stopped before it finished", 5]]);
    expect(rows([researcher("A — x", null)], false, true)).toEqual([["paused", "Waiting for your answer", 5]]);
    expect(rows([researcher("A — x", null)], true)).toEqual([["working", "Checking it's the right organisation", 5]]);
    expect(rows([researcher("A — x", JSON.stringify({ status: "not_found" }))])).toEqual([["notFound", "Couldn't find it", 100]]);
    expect(rows([researcher("A — x", JSON.stringify({ status: "wrong_entity" }))])).toEqual([
      ["wrong", "Found a different organisation", 100],
    ]);
    expect(rows([researcher("A — x", JSON.stringify({ stopped_reason: "Hit the reading limit" }))])).toEqual([
      ["ready", "Stopped at the reading limit", 100],
    ]);
    expect(rows([researcher("A — x", "prose, not JSON")])).toEqual([["ready", "Done", 100]]);
  });

  it("says what a working researcher is doing from its own steps", () => {
    const t = researcher("A — x", null);
    const goals = step("research_goals", { name: "A" }, "x -> y", { lane: "L" });
    const now = (extra: TraceStep[]) => boardOf([t, goals, ...extra], true).rows[0]!;

    expect(now([]).now).toBe("Looking for sources");
    expect(now([]).pct).toBe(15);
    const saving = now([step("save_research", { findings: { entity_name: "A", findings: [{ concept: "x" }] } }, "ok", { lane: "L" })]);
    expect([saving.now, saving.pct, saving.found]).toEqual(["Writing up", 90, 1]);
  });

  it("lists documents, keeping only a scan or failure of a downloaded file", () => {
    const t = researcher("A — x", null);
    const board = boardOf(
      [
        t,
        step("fetch_document", { url: "https://www.a.org/r.pdf", filename: "annual_report.pdf" }, "Saved", { lane: "L", doneAt: 1 }),
        step("read_document_pages", { filename: "annual_report.pdf" }, "page text", { lane: "L", doneAt: 2 }),
        step("read_document_pages", { filename: "scan.pdf" }, "This PDF is most likely scanned", { lane: "L", doneAt: 3 }),
        step("fetch_document", { url: "https://b.org/x.pdf" }, "ERROR: Client error '403 Forbidden' for url 'x'", {
          lane: "L", doneAt: 4,
        }),
        step("read_page", { url: "not a url" }, "ok", { lane: "L", doneAt: 5 }),
      ],
      true,
      { L: t.id },
    );
    expect(board.rows[0]!.pages.map((p) => [p.title, p.where, p.state, p.text])).toEqual([
      ["annual report", "a.org", "read", "Read"],
      ["scan", "", "scanned", "Scanned — no text to read"],
      ["A document", "b.org", "blocked", "Couldn't open — the site said no"],
      ["not a url", "", "read", "Read"],
    ]);
    expect(board.pagesRead).toBe(2);
    expect(board.events.map((e) => e.text)).toEqual([
      "read not a url",
      "couldn't open A document from b.org",
      "opened scan: it is a scan, with no text to read",
      "read annual report from a.org",
    ]);
  });

  it("works with no rows and no lanes, and reports a vault reader", () => {
    const board = boardOf(
      [
        step("task", { subagent_type: "vault-reader" }, JSON.stringify({ documents_read: [1, 2], concepts_found: ["a"] })),
        step("fetch_document", { filename: "plan.pdf" }, null),
      ],
      true,
    );
    expect(board).toMatchObject({ rows: [], ready: 0, pct: 0, attributed: false, now: "Reading: plan" });
    expect(board.events.map((e) => e.text)).toEqual(["Read 2 Doc Vault documents: 1 answer"]);
  });

  it("updates one row when the same organisation is researched again", () => {
    const board = boardOf([researcher("KABIL — first", null), researcher("kabil — again", "{}")], false);
    expect(board.rows.map((r) => [r.name, r.state])).toEqual([["kabil", "ready"]]);
  });
});
