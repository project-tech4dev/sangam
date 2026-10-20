import { describe, expect, it } from "vitest";
import type { TraceStep } from "@/lib/useAgentChat";
import { failuresOf } from "../failures";

const step = (id: string, tool: string, args: unknown, result: string | null): TraceStep => ({ id, tool, args, result, running: false });

describe("failuresOf", () => {
  it("groups identical failures into one line with a count", () => {
    const err = "ERROR: Client error '404 Not Found' for url 'x'";
    const out = failuresOf([
      step("1", "search_public_sources", { query: "rfp" }, err),
      step("2", "search_public_sources", { query: "rfp" }, err),
      step("3", "search_public_sources", { query: "csr" }, err),
    ]);
    expect(out).toEqual([
      { id: "1", label: "Searching the public web", detail: "rfp", note: "the page isn't there", count: 2 },
      { id: "3", label: "Searching the public web", detail: "csr", note: "the page isn't there", count: 1 },
    ]);
  });

  it("leaves out successes and what the Working board already shows", () => {
    expect(
      failuresOf([
        step("1", "read_page", { url: "https://x.org" }, "ERROR: boom"),
        step("2", "task", {}, "REFUSED: no"),
        step("3", "funder_dossier", { name: "Tata" }, "All good"),
        step("4", "funder_dossier", { name: "Tata" }, null),
      ]),
    ).toEqual([]);
  });
});
