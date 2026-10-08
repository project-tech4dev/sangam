/** The coverage_report text (backend/app/ingest/coverage.py `render`), read back into numbers for the chart. */

export type ConceptCoverage = { concept: string; found: number; missing: number; fields: string; note: string };

export type CoverageData = {
  entity: string;
  found: number;
  total: number;
  pct: string;
  fields: string;
  reasons: string;
  concepts: ConceptCoverage[];
};

const ROW = /^(\S+)\s+(\d+\/\d+|✓|–)\s+(\d+\/\d+)\s+(.*)$/;

export function parseCoverage(text: string | null): CoverageData | null {
  if (!text) return null;
  const lines = text.split("\n");
  const head = /^Coverage: (.*)$/.exec(lines[0] ?? "");
  const totals = /^Concepts (\d+)\/(\d+) \((\S+)\) · Fields (.*)$/.exec(lines[1] ?? "");
  if (!head || !totals) return null;
  const concepts: ConceptCoverage[] = [];
  for (const line of lines.slice(5)) {
    const m = ROW.exec(line);
    if (!m) continue;
    const [, concept, years, fields, note] = m;
    const [found, of] = years === "✓" ? [1, 1] : years === "–" ? [0, 1] : years!.split("/").map(Number);
    concepts.push({ concept: concept!, found: found!, missing: of! - found!, fields: fields!, note: note! });
  }
  return {
    entity: head[1]!,
    found: Number(totals[1]),
    total: Number(totals[2]),
    pct: totals[3]!,
    fields: totals[4]!,
    reasons: lines[2] ?? "",
    concepts,
  };
}
