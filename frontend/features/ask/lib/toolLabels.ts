type ToolLabel = { label: string; detail: (args: any) => string };

const TOOL_LABELS: Record<string, ToolLabel> = {
  search_graph: { label: "Querying the knowledge graph", detail: (a) => `search_graph · “${a?.query ?? ""}”` },
  fetch_url: { label: "Fetching a web page", detail: (a) => a?.url ?? "" },
  db_list_tables: { label: "Checking what data exists", detail: () => "db_list_tables" },
  db_describe_table: {
    label: "Reading the table structure",
    detail: (a) => `db_describe_table · ${a?.tables ?? ""}`,
  },
  db_profile_column: {
    label: "Checking how values are stored",
    detail: (a) => `db_profile_column · ${[a?.table, a?.column].filter(Boolean).join(".")}`,
  },
  // `purpose` reads better than raw SQL in a one-line label. The rail shows the SQL that
  // actually ran, which is the half that makes the answer auditable.
  db_query: { label: "Running a query", detail: (a) => a?.purpose ?? a?.sql ?? "" },
  read_file: {
    label: "Reading a skill",
    detail: (a) => (a?.file_path ?? "").split("/").at(-2) ?? "",
  },
  ls: { label: "Listing skills", detail: () => "" },
  read_proposal: { label: "Reading the proposal", detail: (a) => a?.part || "the outline" },
  advance_step: { label: "Moving to the next step", detail: () => "" },
  read_match: { label: "Reading the Funder Match", detail: () => "" },
  read_org_record: { label: "Reading the organisation's record", detail: () => "" },
  compare_fit: {
    label: "Comparing funders",
    detail: (a) => `org ${a?.org_id ?? ""}` + (a?.funder_ids?.length ? ` · funders ${a.funder_ids.join(", ")}` : " · every funder"),
  },
};

export function humanizeTool(name: string): ToolLabel {
  return (
    TOOL_LABELS[name] ?? {
      label: name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()),
      detail: () => name,
    }
  );
}
