import { describe, expect, it } from "vitest";
import type { RegistryIndex } from "@/features/ask/lib/citations";
import { executedSql, hostOf, MAX_SOURCES, sourcesFor, sourcesSkipped, tablesRead } from "@/features/ask/lib/sources";
import type { TraceStep, Turn } from "@/features/ask/lib/useSangamChat";

const q = (result: string | null, args: unknown = {}): TraceStep => ({ id: "q", tool: "db_query", args, result, running: false });
const turn = (steps: TraceStep[], answer = ""): Turn => ({ id: "t", question: "", steps, answer, streaming: false });

const RESULT = [
  "2 row(s). tables: orgs, org_locations.",
  "| id | name |",
  "sources: 3",
  "  orgs · https://ngodarpan.gov.in/a · NGO Darpan · 2026-09-01",
  "  orgs · https://kabil.org/about · 2026-08-02",
  "  org_locations · not-a-url · Somewhere",
  "  org_locations · https://ngodarpan.gov.in/a · NGO Darpan · 2026-09-01",
  "after the block",
].join("\n");

describe("query trace readers", () => {
  it("prefers the executed line, then the model's SELECT", () => {
    expect(executedSql(q("executed: SELECT 1\n1 row(s)."))).toBe("SELECT 1");
    expect(executedSql(q("1 row(s).", { sql: "SELECT 2" }))).toBe("SELECT 2");
    expect(executedSql(q("", {}))).toBeNull();
    expect(executedSql({ ...q(""), tool: "db_list_tables" })).toBeNull();
  });

  it("reads why sources were skipped", () => {
    expect(sourcesSkipped(q("sources: none — aggregated"))).toBe("aggregated");
    expect(sourcesSkipped(q("sources: none"))).toBeNull();
    expect(sourcesSkipped(q("nothing"))).toBeNull();
  });

  it("reads the tables from the header", () => {
    expect(tablesRead(q(RESULT))).toEqual(["orgs", "org_locations"]);
    expect(tablesRead(q(null))).toEqual([]);
  });

  it("hostOf drops www and survives a bad url", () => {
    expect(hostOf("https://www.axisbank.com/csr")).toBe("axisbank.com");
    expect(hostOf("not a url")).toBe("not a url");
  });
});

describe("sourcesFor", () => {
  const index: RegistryIndex = {
    orgs: new Map([
      [1, { slug: "kabil", name: "KABIL", sourceUrl: "https://kabil.org/about", sourceName: "KABIL site" }],
      [2, { slug: "x", name: "Org X" }],
    ]),
    funders: new Map([[5, { slug: "f", name: "Funder F", sourceUrl: "https://f.org", fetchedAt: "2026-07-01T10:00:00Z" }]]),
    scores: new Map([[7, { funderSlug: "f", orgName: "KABIL", funderName: "Funder F", rubricVersion: "v2" }]]),
    activities: new Map([[8, { href: "/x", title: "A partnership", sourceName: "Annual report" }]]),
  };

  it("is empty without a turn", () => {
    expect(sourcesFor(null, index)).toEqual([]);
  });

  it("gathers facts, web reads and cited rows, deduped by url", () => {
    const sources = sourcesFor(
      turn(
        [q(RESULT), { id: "w", tool: "fetch_url", args: { url: "https://www.example.com/p" }, result: "", running: false }],
        "[org:1] [org:2] [funder:5] [score:7] [score:99] [activity:8] [org:404] [news:3]",
      ),
      index,
    );
    expect(sources).toEqual([
      { url: "https://ngodarpan.gov.in/a", label: "NGO Darpan", detail: "orgs", fetchedAt: "2026-09-01", grain: "fact" },
      { url: "https://kabil.org/about", label: "orgs", detail: "orgs", fetchedAt: "2026-08-02", grain: "fact" },
      { url: "https://www.example.com/p", label: "example.com", detail: "read from the web", fetchedAt: null, grain: "web" },
      { url: null, label: "no source recorded", detail: "Org X", fetchedAt: null, grain: "entity" },
      { url: "https://f.org", label: "source on file", detail: "Funder F", fetchedAt: "2026-07-01", grain: "entity" },
      { url: null, label: "Sangam rubric v2", detail: "KABIL × Funder F", fetchedAt: null, grain: "entity" },
      { url: null, label: "Sangam's own rubric", detail: "score #99", fetchedAt: null, grain: "entity" },
      { url: null, label: "Annual report", detail: "A partnership", fetchedAt: null, grain: "entity" },
    ]);
  });

  it("caps the rail at ten", () => {
    expect(MAX_SOURCES).toBe(10);
  });
});
