import type { TraceStep } from "@/lib/useAgentChat";

/**
 * A run's stages, derived from the tool calls that actually happened.
 *
 * The researchers' own calls are in this list: AG-UI's default subagent
 * visibility is "inline", so a subagent's tools stream as the parent's work.
 * That is what makes a live milestone possible at all — but it also means a
 * host cannot be attributed to one researcher, which is why these are stages
 * of the RUN and the per-organisation view stays on the subagent board.
 */
export type MilestoneState = "pending" | "active" | "done" | "skipped";

export type Milestone = {
  key: string;
  label: string;
  /** What actually happened, in the user's terms — never a tool name. */
  detail: string;
  state: MilestoneState;
  /** Shown as chips: the hosts read, the organisations saved. */
  items: string[];
};

const CATALOG_TOOLS = ["research_goals", "funder_dossier"];
// Searching is discovery, not reading: it finds candidate URLs and opens
// none. Counting it here ticked the stage for a run that read nothing.
const SEARCH_TOOLS = ["search_public_sources"];
const READING_TOOLS = ["read_page", "fetch_document", "read_document_pages"];

function host(url?: string): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** A tool result that is a refusal or an error did not accomplish the stage. */
function succeeded(step: TraceStep): boolean {
  if (step.result === null) return false;
  const first = step.result.trim().split("\n")[0] ?? "";
  return !(first.startsWith("REFUSED:") || first.startsWith("ERROR:") || first.includes("failed:"));
}

/**
 * The backend writes this when `save_research` publishes the brief it saved.
 * A backend test pins the phrase, because this is the one place the UI reads
 * a tool's prose rather than its name.
 */
const PUBLISHED = /brief is published/i;

export function milestonesOf(steps: TraceStep[], running: boolean): Milestone[] {
  const of = (names: string[]) => steps.filter((s) => names.includes(s.tool));

  const checked = of(CATALOG_TOOLS);
  // All of them decide the STATE (one still running means "reading now"); only
  // the ones that came back decide the hosts. A refused source was never read,
  // and listing it as one we pulled information from is a lie about provenance.
  const searched = of(SEARCH_TOOLS);
  const read = of(READING_TOOLS);
  const readOk = read.filter(succeeded);
  const saved = of(["save_research"]).filter(succeeded);
  const published = [
    ...saved.filter((s) => PUBLISHED.test(s.result ?? "")),
    ...of(["publish_brief"]).filter(succeeded),
  ];
  const promoted = of(["promote_research"]).filter(succeeded);
  const imported = of(["run_import_now"]).filter(succeeded);
  const written = [...promoted, ...imported];

  const hosts = [...new Set(readOk.map((s) => host((s.args as any)?.url)).filter(Boolean))];
  const refused = read.filter((s) => !s.running && !succeeded(s)).length;
  const names = [
    ...new Set(checked.map((s) => (s.args as any)?.name).filter(Boolean) as string[]),
  ];
  const organisations = [
    ...new Set(
      saved.map((s) => (s.args as any)?.findings?.entity_name).filter(Boolean) as string[],
    ),
  ];

  // A stage never reached is only a FAILURE once a later stage has run: a run
  // that has not got to the sources yet has not skipped the catalog.
  const state = (group: TraceStep[], laterRan: boolean): MilestoneState => {
    if (group.some((s) => s.running)) return "active";
    if (group.length > 0) return "done";
    return laterRan && !running ? "skipped" : "pending";
  };

  return [
    {
      key: "catalog",
      label: "Checked what we already hold",
      detail: names.length > 0 ? names.join(", ") : "the catalog was not consulted first",
      state: state(checked, read.length > 0),
      items: names,
    },
    {
      key: "sources",
      label: "Pulled information from",
      detail:
        hosts.length > 0
          ? `${hosts.length} site${hosts.length === 1 ? "" : "s"}` +
            (refused > 0 ? ` · ${refused} refused or failed` : "")
          : read.some((s) => s.running)
            ? "opening the first source"
            : read.length > 0
              ? "every source it tried was refused or failed"
              : searched.length > 0
                ? "searched, but opened nothing"
                : "no public source was read",
      // A tick beside "everything was refused" is the contradiction worth
      // avoiding: nothing was read, so the stage is not done. A search that
      // opened nothing is the same case — discovery is not evidence.
      state:
        hosts.length > 0
          ? read.some((s) => s.running)
            ? "active"
            : "done"
          : read.length + searched.length > 0
            ? running
              ? "active"
              : "skipped"
            : state(read, saved.length > 0),
      items: hosts,
    },
    {
      key: "saved",
      label: "Saved the findings",
      detail:
        organisations.length > 0
          ? `${organisations.length} organisation${organisations.length === 1 ? "" : "s"}, with the evidence for each fact`
          : "nothing was saved",
      // Only `promoted`, not `written`: an adapter run writes straight through
      // and never saves research, so counting it would accuse the import path
      // of skipping a step it does not have.
      state: state(saved, promoted.length > 0),
      items: organisations,
    },
    {
      key: "published",
      label: "Saved the brief to the bucket",
      detail:
        published.length > 0
          ? `${published.length} brief${published.length === 1 ? "" : "s"} — the funder page links it`
          : "no brief was published",
      // Publishing rides on save_research, so a save that happened without it
      // means Storage is off — worth showing, never worth calling a failure.
      state: published.length > 0 ? "done" : saved.length > 0 && !running ? "skipped" : "pending",
      items: [],
    },
    {
      key: "catalog-write",
      label: "Written into the catalog",
      detail:
        promoted.length > 0
          ? "promoted — see the organisations above for what was held back"
          : imported.length > 0
            ? "written by an import run — see its summary for what was queued"
            : "still research only; nothing was promoted",
      state: state(written, false),
      items: [],
    },
  ];
}
