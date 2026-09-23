"use client";

import { extractCitations, citationTarget, type RegistryIndex } from "../lib/citations";
import { HIDDEN_TOOLS, humanizeTool } from "../lib/toolLabels";
import type { Turn } from "../lib/useSangamChat";
import { CitationChip } from "./AnswerCard";

type Stats = Record<string, number>;

function IndexCard({ stats }: { stats: Stats | null }) {
  const rows: [string, number | undefined][] = [
    ["CSOs in the base", stats?.orgs],
    ["Funders tracked", stats?.funders],
    ["Fit scores recorded", stats?.fit_scores],
    ["Grants recorded", stats?.grants],
    ["Documents on file", stats?.documents],
    ["News signals", stats?.news_mentions],
    ["Districts covered", stats?.districts_covered],
  ];
  return (
    <div className="card" style={{ gap: 8 }}>
      <div className="card-kicker">What&apos;s in the base</div>
      {rows.map(([label, value]) => (
        <div key={label} style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5 }}>
          <span className="muted">{label}</span>
          <strong>{value ?? "—"}</strong>
        </div>
      ))}
    </div>
  );
}

export function EvidenceRail({
  latest,
  stats,
  index,
}: {
  latest: Turn | null;
  stats: Stats | null;
  index: RegistryIndex | null;
}) {
  const steps = latest?.steps.filter((s) => !HIDDEN_TOOLS.has(s.tool) && s.result) ?? [];

  return (
    <aside style={{ width: 340, flexShrink: 0, position: "sticky", top: 84, alignSelf: "flex-start", display: "flex", flexDirection: "column", gap: 12 }}>
      {steps.length === 0 ? (
        <IndexCard stats={stats} />
      ) : (
        <div className="card" style={{ gap: 10 }}>
          <div className="card-kicker">What this answer read</div>
          {steps.map((step) => {
            const label = humanizeTool(step.tool);
            const cites = extractCitations(step.result ?? "").slice(0, 6);
            return (
              <div key={step.id} style={{ borderTop: "1px solid var(--color-divider)", paddingTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>{label.label}</div>
                <div className="muted-2" style={{ fontSize: 11.5 }}>{label.detail(step.args)}</div>
                {cites.length > 0 && (
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {cites.map((cite) => (
                      <CitationChip key={`${cite.kind}:${cite.id}`} href={`sangam://${cite.kind}/${cite.id}`} index={index} />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      <div className="card" style={{ background: "var(--color-accent-2-100)", border: "none", padding: 14 }}>
        <div style={{ fontSize: 11.5, color: "var(--color-accent-2-900)" }}>
          Every claim in an answer carries a citation into the Registry. If it isn&apos;t in the base,
          Sangam says so instead of guessing.
        </div>
      </div>
    </aside>
  );
}
