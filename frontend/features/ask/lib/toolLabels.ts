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
  match_funders: { label: "Ranking funders", detail: (a) => `match_funders · ${a?.org ?? ""}` },
  explain_match: {
    label: "Checking the match",
    detail: (a) => `explain_match · ${a?.org ?? ""} × ${(a?.funders ?? []).join(", ")}`,
  },
  get_org: { label: "Reading the organisation's record", detail: (a) => `get_org · ${a?.org ?? ""}` },
  get_funder: { label: "Reading the funder's record", detail: (a) => `get_funder · ${a?.funder ?? ""}` },
  find_funders: {
    label: "Finding funders",
    detail: (a) =>
      `find_funders · ${[...(a?.places ?? []), ...(a?.themes ?? []), ...(a?.funder_types ?? [])].join(", ")}`,
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
