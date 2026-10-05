"use client";

import type { RegistryIndex } from "../lib/citations";
import { phasesFor } from "../lib/phases";
import { executedSql, hostOf, sourcesFor, sourcesSkipped, tablesRead, type Source } from "../lib/sources";
import type { Turn } from "../lib/useSangamChat";

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
        <div key={label} style={{ display: "flex", justifyContent: "space-between", fontSize: "var(--fs-xs)" }}>
          <span className="muted">{label}</span>
          <strong>{value ?? "—"}</strong>
        </div>
      ))}
    </div>
  );
}

const ROW = { display: "flex", flexDirection: "column", gap: 3, fontSize: "var(--fs-xs)" } as const;

function SourceRow({ source }: { source: Source }) {
  const title = source.fetchedAt ? `${source.label} · fetched ${source.fetchedAt}` : source.label;
  return (
    <div style={ROW}>
      {source.url ? (
        <a href={source.url} target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}>
          {hostOf(source.url)}
        </a>
      ) : (
        <span className="muted" style={{ fontWeight: 600 }}>
          {source.label}
        </span>
      )}
      <span className="muted-2">{source.url ? title : source.detail}</span>
      {source.url && <span className="muted-2">{source.detail}</span>}
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
  const phases = phasesFor(latest);
  const sources = sourcesFor(latest, index);
  const queries = (latest?.steps ?? []).filter((s) => s.tool === "db_query");
  // Named even when provenance could not be: an aggregate still read something.
  const tables = [...new Set(queries.flatMap(tablesRead))];
  const skipped = [...new Set(queries.map(sourcesSkipped).filter(Boolean))] as string[];

  return (
    <aside style={{ width: 340, flexShrink: 0, height: "100%", overflowY: "auto", display: "flex", flexDirection: "column", gap: 12 }}>
      {phases.length === 0 && <IndexCard stats={stats} />}

      {phases.length > 0 && (
        <div className="card" style={{ gap: 10 }}>
          <div className="card-kicker">What Sangam is doing</div>
          {phases.map((phase) => (
            <div key={phase.id} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
              <span
                className={phase.state === "active" ? "ask-pulse" : undefined}
                aria-hidden
                style={{
                  width: 18,
                  height: 18,
                  marginTop: 1,
                  borderRadius: "50%",
                  flexShrink: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "var(--fs-xs)",
                  color: "#fff",
                  background:
                    phase.state === "active" ? "var(--color-accent-500)" : "var(--color-accent-2-600)",
                }}
              >
                {phase.state === "active" ? "" : "✓"}
              </span>
              <div style={{ ...ROW, minWidth: 0 }}>
                <span style={{ fontWeight: 600 }}>
                  {phase.title}
                  {phase.steps > 1 && <span className="muted-2"> · {phase.steps}</span>}
                </span>
                {phase.note && <span className="muted-2">{phase.note}</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      {(sources.length > 0 || tables.length > 0) && (
        <div className="card" style={{ gap: 10 }}>
          <div className="card-kicker">Sources</div>
          {sources.map((source) => (
            <div
              key={source.url ?? `${source.label}|${source.detail}`}
              style={{ borderTop: "1px solid var(--color-divider)", paddingTop: 8 }}
            >
              <SourceRow source={source} />
            </div>
          ))}
          {skipped.length > 0 && (
            <div className="muted-2" style={{ fontSize: "var(--fs-xs)", borderTop: "1px solid var(--color-divider)", paddingTop: 8 }}>
              Some rows carry no source of their own: {skipped.join("; ")}.
              {tables.length > 0 && ` Read from ${tables.join(", ")}.`}
            </div>
          )}
          {sources.length === 0 && skipped.length === 0 && tables.length > 0 && (
            <div className="muted-2" style={{ fontSize: "var(--fs-xs)" }}>
              Read from {tables.join(", ")}; no source URL is recorded for those rows.
            </div>
          )}
        </div>
      )}

      {queries.length > 0 && (
        <div className="card" style={{ gap: 8 }}>
          <div className="card-kicker">How it was queried</div>
          {queries.map((step, i) => {
            const sql = executedSql(step);
            if (!sql) return null;
            return (
              <details key={step.id} style={{ fontSize: "var(--fs-xs)" }}>
                <summary style={{ cursor: "pointer" }}>
                  Query {i + 1}
                  {queries.length > 1 ? ` of ${queries.length}` : ""}
                </summary>
                <pre
                  style={{
                    margin: "6px 0 0",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    fontSize: "var(--fs-xs)",
                    color: "var(--color-neutral-700)",
                  }}
                >
                  {sql}
                </pre>
              </details>
            );
          })}
        </div>
      )}

      <div className="card" style={{ background: "var(--color-accent-2-100)", border: "none", padding: 14 }}>
        <div style={{ fontSize: "var(--fs-xs)", color: "var(--color-accent-2-900)" }}>
          Every claim in an answer carries a citation into the Registry. If it isn&apos;t in the base,
          Sangam says so instead of guessing.
        </div>
      </div>
    </aside>
  );
}
