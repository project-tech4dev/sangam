type ToolLabel = { label: string; detail: (args: any) => string };

const TOOL_LABELS: Record<string, ToolLabel> = {
  search_orgs: { label: "Searching the registry", detail: (a) => `search_orgs · “${a?.query ?? ""}”` },
  get_funder: { label: "Reading the funder profile", detail: (a) => `get_funder · ${a?.name ?? ""}` },
  get_grants: {
    label: "Pulling funding relationships",
    detail: (a) => `get_grants · ${[a?.org, a?.funder, a?.status].filter(Boolean).join(" × ") || "all"}`,
  },
  get_fit_scores: {
    label: "Reading rubric fit scores",
    detail: (a) => `get_fit_scores · ${[a?.org, a?.funder].filter(Boolean).join(" × ")}`,
  },
  search_graph: { label: "Querying the knowledge graph", detail: (a) => `search_graph · “${a?.query ?? ""}”` },
  fetch_url: { label: "Fetching a web page", detail: (a) => a?.url ?? "" },
  write_todos: { label: "Planning the approach", detail: () => "write_todos" },
  task: { label: "Delegating a sub-task", detail: () => "task" },
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
