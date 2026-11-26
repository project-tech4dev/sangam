import { describe, expect, it } from "vitest";
import { runState, statusOf, stepsOf, summaryOf, verdictOf, type CheckRun, type SourceCheck } from "../changeCheck";

const run = (over: Partial<CheckRun> = {}): CheckRun => ({
  run_id: "r1",
  slug: "apf",
  depth: "free",
  decision: "nothing to do",
  started_at: "2026-11-19T08:00:00Z",
  finished_at: "2026-11-19T08:01:00Z",
  error: null,
  refresh_row_id: null,
  refresh_summary: null,
  requested_by: "dev@sangam.local",
  sources: 4,
  ...over,
});

describe("verdictOf", () => {
  it.each([
    ["nothing to do", "none"],
    ["needs the judge", "judge"],
    ["refresh", "update"],
    ["full pull", "research"],
  ])("%s → %s", (decision, next) => {
    expect(verdictOf(run({ decision })).next).toBe(next);
  });

  it("an update already saved points to review, not another update", () => {
    const v = verdictOf(run({ decision: "refresh", refresh_row_id: 91, refresh_summary: "1 updated" }));
    expect(v).toEqual({ title: "Update saved for review", text: "1 updated", next: "none" });
  });

  it("says why an update was not saved, and does not offer it again", () => {
    const v = verdictOf(run({ decision: "refresh", refresh_row_id: null,
                              refresh_summary: "apf: no refresh: it was already researched today" }));
    expect(v).toEqual({ title: "No update saved", text: "apf: no refresh: it was already researched today", next: "none" });
  });

  it("does not say the facts still hold when a source could not be opened", () => {
    const c = (status: string) => ({ status }) as SourceCheck;
    const some = verdictOf({ ...run(), checks: [c("unchanged"), c("unverified"), c("unverified")] });
    expect(some).toEqual({
      title: "Nothing changed on the sources Sangam could open",
      text: "2 sources could not be opened, so not everything was checked. Try again later.",
      next: "none",
    });
    const all = verdictOf({ ...run(), checks: [c("unverified")] });
    expect(all.title).toBe("No source could be opened");
    expect(all.text).toBe("1 source could not be opened, so nothing was checked. Try again later.");
    expect(verdictOf({ ...run(), checks: [c("unchanged")] }).title).toBe("Nothing to do");
  });

  it("a run with no decision yet is still checking", () => {
    expect(verdictOf(run({ decision: null, finished_at: null }))).toEqual({ title: "Checking…", text: "", next: "none" });
  });

  it("a failed run says why and offers nothing", () => {
    expect(verdictOf(run({ error: "RuntimeError: site down" }))).toMatchObject({ next: "none", text: "RuntimeError: site down" });
  });
});

describe("statusOf", () => {
  it("names each status in words", () => {
    expect(statusOf("unverified").label).toBe("Couldn't open");
    expect(statusOf("dead").label).toBe("Page gone");
    expect(statusOf("something-else").label).toBe("something-else");
  });

  it.each([
    ["unchanged", "Unchanged", "tag-neutral"],
    ["minor", "Minor edit", "tag-neutral"],
    ["differs", "Text differs", "tag-accent"],
    ["changed", "Changed", "tag-accent"],
    ["new", "New source", "tag-accent-2"],
  ])("%s reads as %s", (status, label, tag) => {
    expect(statusOf(status)).toEqual({ label, tag });
  });
});

const source = (over: Partial<SourceCheck> = {}): SourceCheck => ({
  url: "https://a.org/report.pdf", status: "unchanged", detail: "HTTP 200", findings_intact: 0, findings_broken: 0,
  findings_unanchored: 0, judge: null, removed_text: [], added_text: [], evidence: null, baseline_snapshot_id: 1,
  new_snapshot_id: null, baseline_seen_at: null, baseline_hash: "8479a3de86ac" + "0".repeat(52),
  today_hash: "8479a3de86ac" + "0".repeat(52), ...over,
});

describe("stepsOf", () => {
  it("an unchanged source stops at the fingerprint, and says why the rest was not needed", () => {
    const steps = stepsOf(source(), "free", 79);
    expect(steps.map((s) => s.state)).toEqual(["done", "done", "skipped", "skipped", "skipped"]);
    expect(steps[1].text).toBe("Same text: kept copy 8479a3de86ac = today 8479a3de86ac.");
    expect(steps[3].text).toBe("Not needed: the text is identical, so all 79 facts still hold.");
  });

  it("a changed source shows the diff, the facts and that a free check asked no AI", () => {
    const steps = stepsOf(source({ status: "changed", today_hash: "ffff" + "0".repeat(60), removed_text: ["a"],
      added_text: ["b", "c"], findings_intact: 3, findings_broken: 1 }), "free", 4);
    expect(steps[1]).toMatchObject({ state: "flag", text: expect.stringContaining("→ today ffff00000000") });
    expect(steps[2].text).toBe("1 paragraph removed, 2 paragraphs added.");
    expect(steps[3]).toEqual({ name: "Check each fact is still there", state: "flag", text: "3 still there · 1 gone or changed · 0 can't tell." });
    expect(steps[4].text).toBe("Not run: a free check never calls the AI.");
  });

  it("the judge's answer, when it ran", () => {
    const steps = stepsOf(source({ status: "minor", judge: { meaningful: false, reason: "footer wording" } }), "full", 2);
    expect(steps[4]).toMatchObject({ state: "done", text: "Doesn't matter: footer wording" });
  });

  it("a source that could not be opened stops there, and is not a change", () => {
    const steps = stepsOf(source({ status: "unverified", detail: "HTTP 403" }), "free", 5);
    expect(steps[0]).toMatchObject({ state: "failed", text: "Couldn't open it (HTTP 403). Not counted as a change." });
    expect(steps.slice(1).every((s) => s.state === "skipped")).toBe(true);
  });
});

describe("summaryOf", () => {
  it("counts how far the sources went", () => {
    const run = { ...({} as CheckRun), checks: [source(), source({ status: "unverified" })] };
    expect(summaryOf(run as never)).toBe("2 sources · 1 opened · 1 same fingerprint · 0 text compared · 0 judged");
  });
});

describe("runState", () => {
  const started = "2026-11-19T08:00:00Z";
  const at = (minutes: number) => new Date(started).getTime() + minutes * 60_000;
  it("a run still inside the backend's window is running; past it, stopped", () => {
    const open = run({ decision: null, finished_at: null, started_at: started });
    expect(runState(open, at(10))).toBe("running");
    expect(runState(open, at(31))).toBe("stopped");
  });
  it("a failed run is failed, a finished one says its decision", () => {
    expect(runState(run({ error: "boom", finished_at: started }))).toBe("failed");
    expect(runState(run({ decision: "refresh", finished_at: started }))).toBe("refresh");
    expect(runState(run({ decision: null, finished_at: started }))).toBe("done");
  });
});
