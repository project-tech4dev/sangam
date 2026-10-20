import { describe, expect, it } from "vitest";
import { humanizeTool } from "@/features/ask/lib/toolLabels";

describe("humanizeTool", () => {
  it("returns the label and detail for a known tool", () => {
    const t = humanizeTool("db_query");
    expect(t.label).toBe("Running a query");
    expect(t.detail({ purpose: "Count orgs", sql: "SELECT 1" })).toBe("Count orgs");
    expect(t.detail({ sql: "SELECT 1" })).toBe("SELECT 1");
    expect(t.detail(undefined)).toBe("");
  });

  it("humanises an unknown tool's name", () => {
    const t = humanizeTool("pull_news_feed");
    expect(t.label).toBe("Pull news feed");
    expect(t.detail({})).toBe("pull_news_feed");
  });

  it("builds each known tool's detail from its args", () => {
    const d = (tool: string, args?: unknown) => humanizeTool(tool).detail(args);
    expect(d("search_graph", { query: "Tata" })).toBe("search_graph · “Tata”");
    expect(d("fetch_url", { url: "https://x" })).toBe("https://x");
    expect(d("db_list_tables")).toBe("db_list_tables");
    expect(d("db_describe_table", { tables: "orgs" })).toBe("db_describe_table · orgs");
    expect(d("db_profile_column", { table: "orgs", column: "state" })).toBe("db_profile_column · orgs.state");
    expect(d("read_file", { file_path: "/skills/funder-matching/SKILL.md" })).toBe("funder-matching");
    expect(d("read_file", {})).toBe("");
    expect(d("read_proposal", { part: "B1" })).toBe("one part");
    expect(d("read_proposal", {})).toBe("the outline");
    expect(d("add_facts", { facts: [1] })).toBe("1 fact");
    expect(d("add_facts", { facts: [1, 2] })).toBe("2 facts");
    expect(d("add_facts", {})).toBe("");
    expect(d("ask_user", { subject: "Budget" })).toBe("Budget");
    expect(d("read_files", { public: true })).toMatch(/public sources/);
    expect(d("read_files", {})).toMatch(/your files/);
    expect(d("read_brief", { side: "org" })).toBe("the organisation");
    expect(d("read_brief", { side: "funder" })).toBe("the funder");
    expect(d("compare_fit", { org_id: 3 })).toBe("org 3 · every funder");
    expect(d("compare_fit", { org_id: 3, funder_ids: [4, 5] })).toBe("org 3 · funders 4, 5");
    for (const tool of ["ls", "advance_step", "write_section", "suggest_edit", "list_funder_documents", "read_funder_document",
      "read_template", "read_vault_document", "read_match", "read_org_record"]) {
      expect(humanizeTool(tool).label, tool).not.toBe(tool);
      expect(typeof d(tool)).toBe("string");
    }
  });
});
