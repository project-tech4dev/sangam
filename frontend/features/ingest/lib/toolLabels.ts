type ToolLabel = { label: string; detail: (args: any) => string };

/** The host, which is what a reader wants to see — not the whole URL. */
function host(url?: string): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function fileLabel(name?: string): string {
  return (name ?? "").replace(/\.pdf$/i, "").replace(/[-_]+/g, " ");
}

/** Sangam Import's own trace labels; Ask Sangam has a separate map. */
const TOOL_LABELS: Record<string, ToolLabel> = {
  // Research: each of these names the site being read, because that is the
  // part a person is entitled to see while the agent works.
  search_public_sources: {
    label: "Searching the public web",
    detail: (a) => a?.query ?? "",
  },
  read_page: { label: "Reading", detail: (a) => host(a?.url) },
  fetch_document: { label: "Downloading a document from", detail: (a) => host(a?.url) },
  read_document_pages: {
    label: "Reading a document",
    detail: (a) =>
      [fileLabel(a?.filename), a?.start_page ? `pages ${a.start_page}–${a.end_page ?? "end"}` : ""]
        .filter(Boolean)
        .join(" · "),
  },
  funder_dossier: {
    label: "Checking what the catalog holds",
    detail: (a) => a?.name ?? "",
  },
  // Registry and import
  list_import_sources: {
    label: "Reading the source registry",
    detail: (a) => a?.detail || a?.category || "all sources",
  },
  plan_import: {
    label: "Planning the run",
    detail: (a) => [a?.funders, a?.years].filter(Boolean).join(" · ") || "every source",
  },
  run_import_now: {
    label: "Importing",
    detail: (a) => [a?.funders, a?.years].filter(Boolean).join(" · ") || a?.goal || "",
  },
  import_run_summary: {
    label: "Reading a run report",
    detail: (a) => (a?.run_id ? `run ${a.run_id}` : "latest run"),
  },
  pending_resolutions: { label: "Checking the review queue", detail: () => "" },
  write_todos: { label: "Planning", detail: () => "" },
  research_goals: {
    label: "Reading what the database expects",
    detail: (a) => a?.name ?? "",
  },
  save_research: {
    label: "Saving findings",
    detail: (a) => a?.findings?.entity_name ?? "",
  },
  publish_brief: {
    label: "Publishing the research brief",
    detail: (a) => a?.slug || "every researched entity",
  },
  promote_research: {
    label: "Writing research into the catalog",
    detail: (a) => a?.slug || "everything not yet promoted",
  },
  read_file: {
    label: "Reading a skill",
    detail: (a) => (a?.file_path ?? "").split("/").at(-2) ?? "",
  },
  ls: { label: "Listing skills", detail: () => "" },
  task: { label: "Delegating a sub-task", detail: () => "" },
};


/** The URL is already in the label beside the note, and often twice in the
 *  message itself. What is left after removing it is the reason. */
function reason(message: string): string {
  const quoted = message.match(/'(\d{3}) ([^']+)'/);
  if (quoted) return `HTTP ${quoted[1]} ${quoted[2]}`;
  const plain = message.match(/\bHTTP (\d{3})\b/);
  if (plain) return `HTTP ${plain[1]}`;
  const text = message.replace(/https?:\/\/\S+/g, "").replace(/\s+/g, " ").trim();
  return text.length > 110 ? `${text.slice(0, 110)}…` : text;
}

/** Refusals and failures are the one thing worth surfacing from a result. */
export function stepNote(result: string | null): string | null {
  if (!result) return null;
  const first = (result.trim().split("\n")[0] ?? "").trim();
  // A refusal is already a written sentence; an error is a traceback fragment.
  if (first.startsWith("REFUSED:")) return reason(first.slice("REFUSED:".length));
  if (first.startsWith("ERROR:") || first.includes("failed:")) return reason(first);
  return null;
}

export function humanizeTool(name: string): ToolLabel {
  return (
    TOOL_LABELS[name] ?? {
      label: name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()),
      detail: () => "",
    }
  );
}
