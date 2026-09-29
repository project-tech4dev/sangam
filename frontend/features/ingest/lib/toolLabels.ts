type ToolLabel = { label: string; detail: (args: any) => string };

/** Sangam Import's own trace labels; Ask Sangam has a separate map. */
const TOOL_LABELS: Record<string, ToolLabel> = {
  list_import_sources: { label: "Reading the source registry", detail: () => "list_import_sources" },
  run_import_now: {
    label: "Importing",
    detail: (a) => `run_import_now · ${a?.sources || "every source"}${a?.limit ? ` · limit ${a.limit}` : ""}`,
  },
  import_run_summary: {
    label: "Reading a run report",
    detail: (a) => `import_run_summary · run ${a?.run_id || "latest"}`,
  },
  pending_resolutions: { label: "Checking the review queue", detail: () => "pending_resolutions" },
  write_todos: { label: "Planning the run", detail: () => "write_todos" },
  task: { label: "Delegating a sub-task", detail: () => "task" },
};

export const HIDDEN_TOOLS = new Set(["ls", "read_file", "write_file", "edit_file", "glob", "grep"]);

export function humanizeTool(name: string): ToolLabel {
  return (
    TOOL_LABELS[name] ?? {
      label: name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()),
      detail: () => name,
    }
  );
}
