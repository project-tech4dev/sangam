"use client";

import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { parseCoverage, type ConceptCoverage } from "../lib/coverage";

/** One coverage_report result as a stacked bar per concept: found vs missing, the reason on hover. */
export function CoverageChart({ text }: { text: string | null }) {
  const data = parseCoverage(text);
  if (!data || data.concepts.length === 0) return null;
  return (
    <section className="card coverage-card" aria-label="Coverage">
      <div className="coverage-head">
        <strong>
          Coverage {data.pct} ({data.found}/{data.total})
        </strong>
        <span className="save-note">{data.entity} · Fields {data.fields}</span>
        <span className="save-note">{data.reasons}</span>
      </div>
      <ResponsiveContainer width="100%" height={data.concepts.length * 24 + 24}>
        <BarChart layout="vertical" data={data.concepts} margin={{ left: 8, right: 8 }}>
          <XAxis type="number" hide allowDecimals={false} />
          <YAxis type="category" dataKey="concept" width={150} tick={{ fontSize: 12 }} />
          <Tooltip content={<Why />} />
          <Bar dataKey="found" stackId="c" name="found" fill="var(--chart-1)" />
          <Bar dataKey="missing" stackId="c" name="missing" fill="var(--chart-5)" />
        </BarChart>
      </ResponsiveContainer>
    </section>
  );
}

function Why({ active, payload }: { active?: boolean; payload?: { payload: ConceptCoverage }[] }) {
  const row = active ? payload?.[0]?.payload : undefined;
  if (!row) return null;
  return (
    <div className="card coverage-tip">
      <strong>{row.concept}</strong>
      <span>
        found {row.found} of {row.found + row.missing} · fields {row.fields}
      </span>
      {row.note !== "–" && <span className="save-note">{row.note}</span>}
    </div>
  );
}
