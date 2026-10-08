import { extractCitations, type RegistryIndex } from "./citations";
import type { TraceStep, Turn } from "./useSangamChat";

/*
 * Where an answer's facts came from, gathered from three places:
 *
 *   fact   — the `sources:` block db_query appends for the tables a query read
 *   web    — a fetch_url step's own argument, because the result does not echo it
 *   entity — the org, funder or activity line a citation marker points at, from the index
 *
 * The `sources:` grammar is a backend contract, pinned by
 * backend/tests/test_sql_render.py::TestSources::test_the_line_grammar_is_a_contract.
 */

/* The rail shows at most this many; the caller renders the remainder as a count rather
 * than dropping it, because a source that vanishes reads as a source that does not exist. */
export const MAX_SOURCES = 10;

export type Source = {
  url: string | null;
  label: string;
  detail: string;
  fetchedAt: string | null;
  grain: "fact" | "web" | "entity";
};

/** The fact grain already arrives as a day; an entity's comes from the REST payload as a
 *  full ISO timestamp. Same list, so same shape. */
function day(value: string | null | undefined): string | null {
  return value ? value.slice(0, 10) : null;
}

/** A tool result is typed `string` here, but the AG-UI protocol also permits content parts. */
function text(step: TraceStep): string {
  return typeof step.result === "string" ? step.result : "";
}

/** The SQL that ran — read from the RESULT, because the validator regenerates the
 *  statement before executing it, so the model's own string is not what hit the database. */
export function executedSql(step: TraceStep): string | null {
  if (step.tool !== "db_query") return null;
  return text(step).match(/^executed: (.+)$/m)?.[1] ?? null;
}

/** Why a query carried no per-row source: aggregated, DISTINCT, UNION or CTE-rooted. */
export function sourcesSkipped(step: TraceStep): string | null {
  return text(step).match(/^sources: none(?: — (.+))?$/m)?.[1] ?? null;
}

/** The tables a query read, from the header, which survives even when provenance cannot. */
export function tablesRead(step: TraceStep): string[] {
  const raw = text(step).match(/^\d+ row\(s\)\. tables: (.+?)\.$/m)?.[1];
  return raw ? raw.split(",").map((t) => t.trim()).filter(Boolean) : [];
}

/** `  table · url · source name · YYYY-MM-DD`, with name and date each optional. */
function parseBlock(step: TraceStep): Source[] {
  const lines = text(step).split("\n");
  const start = lines.findIndex((l) => /^sources: \d+/.test(l));
  if (start < 0) return [];

  const out: Source[] = [];
  for (const line of lines.slice(start + 1)) {
    if (!line.startsWith("  ")) break;
    const [table, url, ...rest] = line.trim().split(" · ");
    if (!table || !url?.startsWith("http")) continue;
    const date = rest.length > 0 && /^\d{4}-\d{2}-\d{2}$/.test(rest[rest.length - 1]!)
      ? rest.pop()!
      : null;
    out.push({ url, label: rest.join(" · ") || table, detail: table, fetchedAt: date, grain: "fact" });
  }
  return out;
}

function entitySources(answer: string, index: RegistryIndex | null): Source[] {
  const out: Source[] = [];
  for (const cite of extractCitations(answer)) {
    const id = Number(cite.id);
    if (cite.kind === "score") {
      const score = index?.scores.get(id);
      out.push({
        url: null,
        // Not a gap: a fit score is Sangam's own rubric judgement, not something read off a page.
        label: score?.rubricVersion ? `Sangam rubric ${score.rubricVersion}` : "Sangam's own rubric",
        detail: score ? `${score.orgName} × ${score.funderName}` : `score #${cite.id}`,
        fetchedAt: null,
        grain: "entity",
      });
      continue;
    }
    const row =
      cite.kind === "org" ? index?.orgs.get(id)
      : cite.kind === "funder" ? index?.funders.get(id)
      : cite.kind === "activity" ? index?.activities.get(id)
      : null;
    if (!row) continue;
    const name = "name" in row ? row.name : row.title;
    out.push({
      url: row.sourceUrl ?? null,
      label: row.sourceName || (row.sourceUrl ? "source on file" : "no source recorded"),
      detail: name,
      fetchedAt: day(row.fetchedAt),
      grain: "entity",
    });
  }
  return out;
}

/** Every source behind one answer, deduped. Keyed on url where there is one, and on the
 *  label otherwise, so two unsourced rows do not collapse into one line. */
export function sourcesFor(turn: Turn | null, index: RegistryIndex | null): Source[] {
  if (!turn) return [];
  const found: Source[] = [];

  for (const step of turn.steps) {
    if (step.tool === "db_query") found.push(...parseBlock(step));
    if (step.tool === "fetch_url") {
      const url = typeof step.args === "object" && step.args
        ? (step.args as Record<string, unknown>).url
        : null;
      if (typeof url === "string" && url) {
        found.push({ url, label: hostOf(url), detail: "read from the web", fetchedAt: null, grain: "web" });
      }
    }
  }
  found.push(...entitySources(turn.answer, index));

  const seen = new Set<string>();
  return found.filter((s) => {
    const key = s.url ?? `${s.label}|${s.detail}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
