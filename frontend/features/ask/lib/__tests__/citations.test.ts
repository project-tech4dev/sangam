import { describe, expect, it } from "vitest";
import { citationTarget, extractCitations, linkifyCitations, type RegistryIndex } from "@/features/ask/lib/citations";

const index: RegistryIndex = {
  orgs: new Map([[1, { slug: "kabil", name: "KABIL" }]]),
  funders: new Map([[2, { slug: "axis-bank-foundation", name: "Axis Bank Foundation" }]]),
  scores: new Map([[3, { funderSlug: "axis-bank-foundation", orgName: "KABIL", funderName: "Axis Bank Foundation" }]]),
  activities: new Map([[4, { href: "/registry/funders/axis-bank-foundation#partners", title: "KABIL partnership" }]]),
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
