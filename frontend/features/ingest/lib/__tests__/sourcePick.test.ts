import { describe, expect, it } from "vitest";
import type { TraceStep } from "@/lib/useAgentChat";
import { EMPTY_SOURCES, nothingChosen, pausedAction, proposedSources, readingFrom, sourcesDecision } from "../sourcePick";

const interrupt = (args: Record<string, unknown>) => ({ action_requests: [{ name: "choose_sources", args }] });

describe("nothingChosen", () => {
  it("is true only when no source is ticked", () => {
    expect(nothingChosen(EMPTY_SOURCES)).toBe(true);
    expect(nothingChosen({ ...EMPTY_SOURCES, web: true })).toBe(false);
    expect(nothingChosen({ ...EMPTY_SOURCES, vault_docs: [1] })).toBe(false);
    expect(nothingChosen({ ...EMPTY_SOURCES, staff_paths: ["a.xlsx"] })).toBe(false);
  });
});

describe("pausedAction", () => {
  it("finds the named action in an object or JSON string", () => {
    expect(pausedAction(interrupt({ web: true }), "choose_sources")?.args).toEqual({ web: true });
    expect(pausedAction(JSON.stringify(interrupt({})), "choose_sources")?.name).toBe("choose_sources");
  });

  it("is null for bad JSON, another tool, or nothing", () => {
    expect(pausedAction("{oops", "choose_sources")).toBeNull();
    expect(pausedAction(interrupt({}), "other")).toBeNull();
    expect(pausedAction(null, "choose_sources")).toBeNull();
  });
});

describe("proposedSources", () => {
  it("defaults web and library on, and cleans the ids and paths", () => {
    expect(proposedSources(interrupt({ vault_org: 4, vault_docs: ["7", "x", 8], staff_paths: ["a.xlsx", 3] }))).toEqual({
      web: true, library: true, vault_org: 4, vault_docs: [7, 8], staff_paths: ["a.xlsx"],
    });
    expect(proposedSources(interrupt({ web: false, library: false, vault_org: "4" }))).toEqual({
      web: false, library: false, vault_org: null, vault_docs: [], staff_paths: [],
    });
  });

  it("is null when the interrupt is not choose_sources", () => {
    expect(proposedSources({ action_requests: [{ name: "other" }] })).toBeNull();
  });
});

describe("sourcesDecision", () => {
  it("always answers with an edit carrying the ticks", () => {
    expect(sourcesDecision(EMPTY_SOURCES)).toEqual({ type: "edit", edited_action: { name: "choose_sources", args: EMPTY_SOURCES } });
  });
});

describe("readingFrom", () => {
  const step = (result: string | null): TraceStep => ({ id: "s", tool: "choose_sources", args: {}, result, running: false });

  it("lists what the answered choose_sources says it reads", () => {
    const result = [
      "Sources for this run:",
      "- public websites: yes",
      "- Sangam's library: yes",
      "- Doc Vault of org 4: documents 7, 8, 9",
      "- team spreadsheet Funders.xlsx → document 12",
      "- team spreadsheet NGOs.xlsx → document 13",
    ].join("\n");
    expect(readingFrom([step(result)])).toBe("Public websites · Sangam's library · Doc Vault (3) · Team spreadsheets (2)");
  });

  it("is null before an answer, after a refusal, or with nothing ticked", () => {
    expect(readingFrom([])).toBeNull();
    expect(readingFrom([step(null)])).toBeNull();
    expect(readingFrom([step("REFUSED: pick one")])).toBeNull();
    expect(readingFrom([step("- public websites: no")])).toBeNull();
  });

  it("uses the latest answer", () => {
    expect(readingFrom([step("- public websites: yes"), step("- Sangam's library: yes")])).toBe("Sangam's library");
  });
});
