type ToolLabel = { label: string; detail: (args: any) => string };

const TOOL_LABELS: Record<string, ToolLabel> = {
  search_graph: { label: "Querying the knowledge graph", detail: (a) => `search_graph · “${a?.query ?? ""}”` },
  fetch_url: { label: "Fetching a web page", detail: (a) => a?.url ?? "" },
  write_todos: { label: "Planning the approach", detail: () => "write_todos" },
  task: { label: "Delegating a sub-task", detail: () => "task" },
  db_list_tables: { label: "Checking what data exists", detail: () => "db_list_tables" },
  db_describe_table: {
    label: "Reading the table structure",
    detail: (a) => `db_describe_table · ${a?.tables ?? ""}`,
  },
  db_profile_column: {
    label: "Checking how values are stored",
    detail: (a) => `db_profile_column · ${[a?.table, a?.column].filter(Boolean).join(".")}`,
  },
  // `purpose` reads better than raw SQL in a one-line label; the query itself is
  // shown in full by the evidence rail, which is what makes the answer auditable.
  db_query: { label: "Running a query", detail: (a) => a?.purpose ?? a?.sql ?? "" },
};

/** deepagents filesystem built-ins — noise in a trace, hidden by default. */
export const HIDDEN_TOOLS = new Set(["ls", "read_file", "write_file", "edit_file", "glob", "grep"]);

export function humanizeTool(name: string): ToolLabel {
  return (
    TOOL_LABELS[name] ?? {
      label: name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()),
      detail: () => name,
    }
  );
}
