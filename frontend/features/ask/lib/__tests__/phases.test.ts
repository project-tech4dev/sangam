import { describe, expect, it } from "vitest";
import { phasesFor } from "@/features/ask/lib/phases";
import type { TraceStep, Turn } from "@/features/ask/lib/useSangamChat";

let n = 0;
const step = (tool: string, args: unknown = {}, running = false): TraceStep => ({
  id: `s${n++}`, tool, args, result: running ? null : "", running,
});
const turn = (steps: TraceStep[]): Turn => ({ id: "t", question: "q", steps, answer: "", streaming: false });

describe("phasesFor", () => {
  it("is empty without a turn", () => {
    expect(phasesFor(null)).toEqual([]);
  });

  it("groups consecutive steps on the same tool and keeps the order they ran", () => {
    const phases = phasesFor(turn([
      step("db_list_tables"),
      step("db_describe_table", { tables: "orgs, funders" }),
      step("db_describe_table", { tables: "grants" }),
      step("read_file", { file_path: "/skills/x/SKILL.md" }),
      step("db_profile_column", { table: "orgs", column: "state" }),
      step("db_query", { purpose: "first" }),
      step("db_query", { purpose: "Count orgs in Assam" }, true),
    ]));
    expect(phases.map((p) => [p.id, p.title, p.steps, p.note, p.state])).toEqual([
      ["discover-0", "Finding the data", 1, "", "done"],
      ["schema-1", "Reading the table structure", 2, "orgs, funders, grants", "done"],
      ["values-2", "Checking how values are stored", 1, "orgs.state", "done"],
      ["query-3", "Querying", 2, "Count orgs in Assam", "active"],
    ]);
  });

  it("tolerates args that are still a partial JSON string", () => {
    const [phase] = phasesFor(turn([step("search_graph", '{"query": "Ass', true)]));
    expect(phase).toMatchObject({ title: "Reading the knowledge graph", note: "", state: "active" });
  });

  it("notes the graph query and the fetched url", () => {
    const phases = phasesFor(turn([step("search_graph", { query: "Tata" }), step("fetch_url", { url: "https://x.org" })]));
    expect(phases.map((p) => p.note)).toEqual(["Tata", "https://x.org"]);
  });

  it("lists a table read twice only once", () => {
    const [phase] = phasesFor(turn([
      step("db_describe_table", { tables: "orgs, funders" }),
      step("db_describe_table", { tables: "funders" }),
    ]));
    expect(phase!.note).toBe("orgs, funders");
  });
});
