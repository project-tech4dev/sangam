import type { FootprintState, Metric, StatedPlace } from "@/lib/api";
import { titleCase } from "@/lib/format";
import { Card, Empty, humanise, num, PTag, shortSource, SourceLink } from "./shared";

/* The latest year's project places, which the hero and the Reach tab both describe. */
export function latestFootprint(footprint: FootprintState[]) {
  // The newest year that names districts; a later year listing only states is a partial report.
  const years = (rows: FootprintState[]) => rows.map((f) => f.fiscal_year).sort();
  const year = years(footprint.filter((f) => f.districts > 0)).at(-1) ?? years(footprint).at(-1) ?? null;
  const rows = footprint.filter((f) => f.fiscal_year === year && f.state);
  return {
    year, rows,
    districts: rows.reduce((n, r) => n + r.districts, 0),
    states: rows.length,
  };
}

const STAGES = ["input", "output", "adoption", "outcome", "sustained_outcome", "impact", "sroi"];
const stageRank = (m: Metric) => (m.stage && STAGES.includes(m.stage) ? STAGES.indexOf(m.stage) : STAGES.length);
const isYear = (period: string | null) => !!period && /^(FY\d{4}-\d{2}|CY\d{4})$/.test(period);

/* Grouped only by stored fields: one measure is one (name, unit, place); a fiscal or calendar year (FY2024-25, CY2025) goes in
   the by-year table, any other period in the second. Nothing is merged by meaning. */
function MetricTables({ metrics }: { metrics: Metric[] }) {
  const byStage = (a: Metric, b: Metric) => stageRank(a) - stageRank(b) || a.name.localeCompare(b.name);
  const yearly = metrics.filter((m) => isYear(m.period));
  const running = metrics.filter((m) => !isYear(m.period)).sort(byStage);
  const years = [...new Set(yearly.map((m) => m.period!))].sort();
  const measures = new Map<string, Metric[]>();
  for (const m of [...yearly].sort(byStage)) {
    const key = `${m.name}|${m.unit ?? ""}|${m.place ?? ""}`;
    measures.set(key, [...(measures.get(key) ?? []), m]);
  }
  const cell = (m: Metric | undefined) => (m ? (
    <>
      {m.value != null ? num(m.value) : "—"}
      {m.target != null && <div className="muted">target {num(m.target)}</div>}
    </>
  ) : <span className="muted">—</span>);
  const label = (m: Metric) => (
    <>{m.name}{m.place ? <span className="muted"> · {m.place}</span> : null}
      {m.unit && <span className="muted"> · {m.unit}</span>}</>
  );

  return (
    <>
      {measures.size > 0 && (
        <div className="profile-table-wrap">
          <table className="profile-table">
            <thead><tr><th>By year</th>{years.map((y) => <th key={y}>{y}</th>)}<th>Source</th></tr></thead>
            <tbody>
              {[...measures.values()].map((rows) => {
                const latest = rows.reduce((a, b) => (a.period! > b.period! ? a : b));
                return (
                  <tr key={rows[0].id}>
                    <td>{label(rows[0])}</td>
                    {years.map((y) => <td key={y} className="profile-num">{cell(rows.find((r) => r.period === y))}</td>)}
                    <td><SourceLink url={latest.source_url} label={shortSource(latest.source_name, latest.source_url)} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {running.length > 0 && (
        <div className="profile-table-wrap">
          <table className="profile-table">
            <thead><tr><th>Totals and other periods</th><th>Value</th><th>Period</th><th>Source</th></tr></thead>
            <tbody>
              {running.map((m) => (
                <tr key={m.id}>
                  <td>{label(m)}</td>
                  <td className="profile-num">{cell(m)}</td>
                  <td className="muted profile-sm">{m.period ?? "—"}</td>
                  <td><SourceLink url={m.source_url} label={shortSource(m.source_name, m.source_url)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export function FunderReach({
  metrics, footprint, stated,
}: {
  metrics: Metric[]; footprint: FootprintState[]; stated: StatedPlace[];
}) {
  const latest = latestFootprint(footprint);
  const source = latest.rows.find((r) => r.source_url);
  // States reported only in another year still show, marked with their year.
  const seen = new Set(latest.rows.map((r) => r.state));
  const others = footprint.filter((f) => f.state && f.fiscal_year !== latest.year && !seen.has(f.state)
    && (seen.add(f.state), true));
  const states = [...latest.rows, ...others];

  return (
    <div className="profile-tab">
      <Card kicker="Reach · the foundation's own figures">
        {metrics.length === 0 ? <Empty>No reach figures recorded yet.</Empty> : (
          <>
            <MetricTables metrics={metrics} />
            {metrics.some((m) => m.method === "self_reported") && (
              <p className="profile-blank muted profile-sm">Self-reported; Sangam has not checked them against partners.</p>
            )}
          </>
        )}
      </Card>

      <Card
        kicker={latest.year ? `Where its projects are · ${latest.year}` : "Where its projects are"}
        aside={source ? <SourceLink url={source.source_url} label={shortSource(source.source_name, source.source_url)} /> : undefined}
      >
        {states.length === 0 ? <Empty>No project places recorded yet.</Empty> : (
          <>
            <div className="profile-stats">
              {latest.districts > 0 && (
                <div><div className="profile-statn">{latest.districts}</div><div className="profile-kicker">Districts</div></div>
              )}
              <div><div className="profile-statn">{latest.states}</div><div className="profile-kicker">States & UTs</div></div>
            </div>
            <div className="profile-grid">
              {states.map((r) => (
                <div key={`${r.state}-${r.fiscal_year}`} className="profile-line">
                  <div className="profile-row">
                    <strong>{r.state}</strong>
                    <span className="muted profile-sm">
                      {r.districts === 0 ? "State only, no district named" : `${r.districts} ${r.districts === 1 ? "district" : "districts"}`}
                      {r.fiscal_year !== latest.year ? ` · ${r.fiscal_year}` : ""}
                    </span>
                  </div>
                  {r.district_names.length > 0 && (
                    <span className="muted profile-sm">{r.district_names.map((d) => titleCase(d)).join(", ")}</span>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
      </Card>

      <Card kicker="Where it says it works">
        {stated.length === 0 ? <Empty>No stated geography recorded yet.</Empty> : stated.map((s) => (
          <div key={`${s.name}-${s.role}`} className="profile-line profile-line-tight">
            <div className="profile-row">
              <strong>{titleCase(s.name)}</strong>
              {s.kind === "district" && s.state && <span className="muted">{s.state}</span>}
              {s.role && <PTag>{humanise(s.role)}</PTag>}
              <SourceLink url={s.source_url} />
            </div>
            {s.note && <span className="muted profile-sm">{s.note}</span>}
          </div>
        ))}
      </Card>
    </div>
  );
}
