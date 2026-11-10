import { describe, expect, it } from "vitest";
import { fileLabel, host, humanizeTool, stepNote } from "../toolLabels";

describe("host", () => {
  it("shows the hostname without www, and passes through what is not a URL", () => {
    expect(host("https://www.tata.com/csr/policy.pdf")).toBe("tata.com");
    expect(host("not a url")).toBe("not a url");
    expect(host(undefined)).toBe("");
  });
});

describe("fileLabel", () => {
  it("drops .pdf and turns separators into spaces", () => {
    expect(fileLabel("CSR_Policy-2025.PDF")).toBe("CSR Policy 2025");
    expect(fileLabel(undefined)).toBe("");
  });
});

describe("humanizeTool", () => {
  it("returns the label and detail for a known tool", () => {
    const t = humanizeTool("read_page");
    expect(t.label).toBe("Reading");
    expect(t.detail({ url: "https://www.example.org/a" })).toBe("example.org");
  });

  it("humanises an unknown tool name", () => {
    const t = humanizeTool("brand_new_tool");
    expect(t.label).toBe("Brand new tool");
    expect(t.detail({})).toBe("");
  });

  it("builds details from the arguments each tool takes", () => {
    expect(humanizeTool("read_document_pages").detail({ filename: "annual_report.pdf", start_page: 3, end_page: 9 }))
      .toBe("annual report · pages 3–9");
    expect(humanizeTool("read_document_pages").detail({ filename: "a.pdf", start_page: 3 })).toBe("a · pages 3–end");
    expect(humanizeTool("read_source_rows").detail({ name: "Funders", sheet: "2025" })).toBe("Funders · 2025");
    expect(humanizeTool("read_library_document").detail({ document_id: 7, start_page: 2 })).toBe("document 7 · from page 2");
    expect(humanizeTool("read_workbook").detail({ documents: [1, 2], sheet: "S" })).toBe("document 1, 2 · S");
    expect(humanizeTool("list_import_sources").detail({})).toBe("all sources");
    expect(humanizeTool("plan_import").detail({})).toBe("every source");
    expect(humanizeTool("plan_import").detail({ funders: "Tata", years: "2024" })).toBe("Tata · 2024");
    expect(humanizeTool("run_import_now").detail({ sources: "funder_calls" })).toBe("Open calls · every funder");
    expect(humanizeTool("run_import_now").detail({ goal: "refresh" })).toBe("refresh");
    expect(humanizeTool("import_run_summary").detail({})).toBe("latest run");
    expect(humanizeTool("import_run_summary").detail({ run_id: 4 })).toBe("run 4");
    expect(humanizeTool("record_registry_check").detail({ org: "KABIL", status: "ok" })).toBe("KABIL · ok");
    expect(humanizeTool("read_vault_document").detail({ document_id: 3 })).toBe("document 3");
    expect(humanizeTool("save_research").detail({ findings: { entity_name: "KABIL" } })).toBe("KABIL");
    expect(humanizeTool("read_file").detail({ file_path: "/skills/entity-record/SKILL.md" })).toBe("entity-record");
    expect(humanizeTool("search_public_sources").detail({ query: "tata csr" })).toBe("tata csr");
  });
});

describe("every known tool", () => {
  const names = (
    "search_public_sources read_page fetch_document read_document_pages read_source_rows choose_sources " +
    "list_library_documents read_library_document read_workbook funder_dossier compare_with_catalog coverage_report " +
    "list_import_sources plan_import run_import_now import_run_summary pending_resolutions record_registry_check " +
    "write_todos research_goals list_vault_documents read_vault_document save_vault_findings save_research " +
    "publish_brief promote_research read_file ls task"
  ).split(" ");

  // A call can stream before its arguments arrive, so a detail must survive none.
  it.each(names)("%s has its own label and a detail that copes with no arguments", (name) => {
    const t = humanizeTool(name);
    expect(t.label).not.toBe(name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()));
    expect(typeof t.detail(undefined)).toBe("string");
    expect(typeof t.detail({})).toBe("string");
  });
});

describe("stepNote", () => {
  it("is null for a plain result", () => {
    expect(stepNote(null)).toBeNull();
    expect(stepNote("Read 4 pages")).toBeNull();
  });

  it("pulls the status out of a quoted HTTP error", () => {
    expect(stepNote("ERROR: Client error '404 Not Found' for url 'https://x.org/a'")).toBe("HTTP 404 Not Found");
  });

  it("keeps a bare HTTP status", () => {
    expect(stepNote("read_page failed: HTTP 503 from https://x.org")).toBe("HTTP 503");
  });

  it("strips URLs from a refusal and keeps only the first line", () => {
    expect(stepNote("REFUSED: https://x.org/a is outside the chosen sources\nmore")).toBe("is outside the chosen sources");
  });

  it("cuts a long reason at 110 characters", () => {
    const note = stepNote(`ERROR: ${"a".repeat(200)}`)!;
    expect(note).toHaveLength(111);
    expect(note.endsWith("…")).toBe(true);
  });
});
