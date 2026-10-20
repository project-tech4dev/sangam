import { describe, expect, it } from "vitest";
import type { TraceStep } from "@/lib/useAgentChat";
import {
  addedOf, completeness, emptyReason, gapDetail, isSaved, profileOf, slugsOf, topicBar, topicLine, wasFound,
} from "../done";
import type { CoverageCell, CoverageConcept, ResearchCoverage } from "../types";

const cell = (status: CoverageCell["status"], detail = ""): CoverageCell => ({ year: null, status, detail });
const concept = (over: Partial<CoverageConcept> = {}): CoverageConcept => ({
  concept: "c", title: "C", cells: [], fields_filled: 0, fields_total: 0, held: 0, extra_years: [],
  added: 0, updated: 0, before: 0, after: 0, ...over,
});
const coverage = (over: Partial<ResearchCoverage> = {}): ResearchCoverage =>
  ({ slug: "kabil", stage: "saved", entity: { kind: "org", status: "ok", id: 3, name: "KABIL" }, concepts: [], ...over }) as ResearchCoverage;

describe("slugsOf", () => {
  it("collects slugs from researcher results and saves, once each, in order", () => {
    const steps: TraceStep[] = [
      { id: "1", tool: "task", args: {}, result: JSON.stringify({ slug: "kabil" }), running: false },
      { id: "2", tool: "task", args: {}, result: "Prose with no slug", running: false },
      { id: "3", tool: "promote_research", args: { slug: "tata" }, result: "ok", running: false },
      { id: "4", tool: "promote_research", args: { slug: "kabil" }, result: "ok", running: false },
      { id: "5", tool: "task", args: {}, result: null, running: true },
      { id: "6", tool: "promote_research", args: { slug: 7 }, result: "ok", running: false },
    ];
    expect(slugsOf(steps)).toEqual(["kabil", "tata"]);
  });
});

describe("isSaved and profileOf", () => {
  it("links an org or a funder once saved with an id", () => {
    expect(isSaved(coverage())).toBe(true);
    expect(profileOf(coverage())).toBe("/registry/3");
    expect(profileOf(coverage({ entity: { kind: "funder", status: "ok", id: 8, name: "Tata" } }))).toBe("/registry/funders/8");
  });

  it("is null before a save or without an id", () => {
    expect(isSaved(coverage({ stage: "planned" }))).toBe(false);
    expect(profileOf(coverage({ stage: "planned" }))).toBeNull();
    expect(profileOf(coverage({ entity: { kind: "funder", status: "new", id: null, name: "Tata" } }))).toBeNull();
    expect(isSaved(coverage({ entity: null }))).toBe(false);
  });
});

describe("topicBar", () => {
  it("splits before into kept and updated, never below zero", () => {
    expect(topicBar(concept({ before: 5, updated: 2, added: 1 }))).toEqual({ kept: 3, updated: 2, added: 1 });
    expect(topicBar(concept({ before: null, updated: 2 }))).toEqual({ kept: 0, updated: 2, added: 0 });
  });
});

describe("emptyReason", () => {
  it("is null when the topic has anything", () => {
    expect(emptyReason(concept({ before: 1 }))).toBeNull();
    expect(emptyReason(concept({ after: 1 }))).toBeNull();
  });

  it("names the most telling reason first", () => {
    expect(emptyReason(concept({ cells: [cell("not_attempted"), cell("blocked")] }))).toBe("Couldn't read");
    expect(emptyReason(concept({ cells: [cell("not_stated")] }))).toBe("Not on their website");
    expect(emptyReason(concept({ cells: [cell("not_written"), cell("blocked")] }))).toBe("Found, nowhere to save it");
    expect(emptyReason(concept({ cells: [cell("found")] }))).toBe("Found, nowhere to save it");
    expect(emptyReason(concept())).toBe("Not found");
  });
});

describe("wasFound, gapDetail and topicLine", () => {
  it("reads what saving did to a topic", () => {
    expect(wasFound(concept({ cells: [cell("found")] }))).toBe(true);
    expect(gapDetail(concept({ cells: [cell("found", "x"), cell("blocked", "403 on the PDF")] }))).toBe("403 on the PDF");
    expect(gapDetail(concept({ cells: [cell("blocked")] }))).toBeNull();
    expect(topicLine(concept({ before: 2, added: 3, updated: 1 }))).toBe("+3 added, 1 updated");
    expect(topicLine(concept({ before: 2 }))).toBe("No change");
    expect(topicLine(concept({ cells: [cell("blocked")] }))).toBe("Couldn't read");
  });
});

describe("completeness and addedOf", () => {
  it("is the share of topics with anything, before and after", () => {
    const c = coverage({
      concepts: [concept({ before: 1 }), concept({ after: 2 }), concept({ added: 1, before: null, after: null }), concept()],
    });
    expect(completeness(c)).toEqual({ before: 0.25, after: 0.75 });
    expect(addedOf(c)).toBe(1);
    expect(completeness(coverage())).toEqual({ before: 0, after: 0 });
  });
});
