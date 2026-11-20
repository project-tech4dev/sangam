import { describe, expect, it } from "vitest";
import { chipText, citationTarget, extractCitations, linkifyCitations, missingCitations, type RegistryIndex } from "@/features/ask/lib/citations";

const index: RegistryIndex = {
  orgs: new Map([[1, { slug: "kabil", name: "KABIL" }]]),
  funders: new Map([[2, { slug: "axis-bank-foundation", name: "Axis Bank Foundation" }]]),
  scores: new Map([[3, { funderSlug: "axis-bank-foundation", orgName: "KABIL", funderName: "Axis Bank Foundation" }]]),
  activities: new Map([
    [4, { href: "/registry/funders/axis-bank-foundation#partners", title: "KABIL partnership" }],
    [5, { href: "/registry/kabil", title: "Axis Bank Foundation → KABIL: Water", short: "Axis Bank Foundation → KABIL" }],
  ]),
};

describe("linkifyCitations", () => {
  it("turns markers into sangam:// links", () => {
    expect(linkifyCitations("KABIL [org:1] fits [funder:2].")).toBe(
      "KABIL [org:1](sangam://org/1) fits [funder:2](sangam://funder/2).",
    );
  });

  it("leaves markers inside inline and fenced code alone", () => {
    const md = "See `[org:1]` and\n```\nSELECT '[funder:2]'\n```\nthen [news:7]";
    expect(linkifyCitations(md)).toBe("See `[org:1]` and\n```\nSELECT '[funder:2]'\n```\nthen [news:7](sangam://news/7)");
  });

  it("ignores unknown kinds", () => {
    expect(linkifyCitations("[user:1]")).toBe("[user:1]");
  });

  it("never marks a chip as named: every chip says its name (#460 follow-up)", () => {
    expect(linkifyCitations("**Kabil** [org:1]")).toBe("**Kabil** [org:1](sangam://org/1)");
  });
});

describe("missingCitations", () => {
  it("lists cited orgs, scores and partner lines the index lacks, once each", () => {
    const text = "KABIL [org:1], Udalguri NGO [org:812] [org:812] [score:3] [score:40] [activity:5] [activity:77] [funder:9] [news:2]";
    expect(missingCitations(text, index)).toEqual({ org: [812], score: [40], activity: [77] });
  });

  it("skips ids a lookup cannot ask for", () => {
    expect(missingCitations("[org:abc] [graph:1f2e3d4c]", index)).toEqual({ org: [], score: [], activity: [] });
  });
});

describe("chipText", () => {
  it("names the row the page holds", () => {
    expect(chipText("org", "1", index)).toBe("KABIL");
    expect(chipText("funder", "2", index)).toBe("Axis Bank Foundation");
    expect(chipText("score", "3", index)).toBe("KABIL × Axis Bank Foundation");
    expect(chipText("activity", "5", index)).toBe("Axis Bank Foundation → KABIL");
    expect(chipText("activity", "4", index)).toBe("KABIL partnership");
  });

  it("says it in words, never a code, when the page has no row", () => {
    expect(chipText("org", "9", null)).toBe("Organisation's record");
    expect(chipText("funder", "9", index)).toBe("Funder's record");
    expect(chipText("score", "9", index)).toBe("Funder Match");
    expect(chipText("activity", "9", index)).toBe("Funding record");
    expect(chipText("grant", "1", index)).toBe("Past grant");
    expect(chipText("news", "1", index)).toBe("News");
    expect(chipText("graph", "abcdef12", index)).toBe("Sangam's links");
  });
});

describe("extractCitations", () => {
  it("lists each marker once, in order of first mention", () => {
    expect(extractCitations("[org:1] and [funder:2], again [org:1], graph [graph:ab12cd34ef]")).toEqual([
      { kind: "org", id: "1" },
      { kind: "funder", id: "2" },
      { kind: "graph", id: "ab12cd34ef" },
    ]);
  });
});

describe("citationTarget", () => {
  it("resolves known rows to their registry pages and names", () => {
    expect(citationTarget("org", "1", index)).toEqual({ href: "/registry/kabil", label: "KABIL" });
    expect(citationTarget("funder", "2", index)).toEqual({ href: "/registry/funders/axis-bank-foundation", label: "Axis Bank Foundation" });
    expect(citationTarget("score", "3", index)).toEqual({
      href: "/registry/funders/axis-bank-foundation",
      label: "KABIL × Axis Bank Foundation",
    });
    expect(citationTarget("activity", "4", index)).toEqual({
      href: "/registry/funders/axis-bank-foundation#partners",
      label: "KABIL partnership",
    });
  });

  it("falls back to the id when the index has no row", () => {
    expect(citationTarget("org", "9", null)).toEqual({ href: "/registry/9", label: "org #9" });
    expect(citationTarget("funder", "9", index)).toEqual({ href: "/registry/funders/9", label: "funder #9" });
    expect(citationTarget("score", "9", index)).toEqual({ href: null, label: "score #9" });
    expect(citationTarget("activity", "9", index)).toEqual({ href: null, label: "funder activity #9" });
  });

  it("renders retired, news and graph markers unlinked", () => {
    expect(citationTarget("grant", "5", index)).toEqual({ href: null, label: "grant #5 (retired)" });
    expect(citationTarget("news", "6", index)).toEqual({ href: null, label: "news story #6" });
    expect(citationTarget("graph", "abcdef1234567", index)).toEqual({ href: null, label: "graph evidence abcdef12" });
  });
});
