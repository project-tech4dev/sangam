import type { ImportRun } from "../lib/types";

function when(iso: string) {
  return new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export function RunHistory({ runs }: { runs: ImportRun[] }) {
  if (runs.length === 0) {
    return (
      <p style={{ fontSize: "var(--fs-sm)", color: "var(--color-muted)" }}>
        No import has run yet. Ask below to start one.
      </p>
    );
  }
  return (
    <section>
      <h2 style={{ fontSize: "var(--fs-lg)", margin: "0 0 10px" }}>Recent runs</h2>
      <div style={{ display: "grid", gap: 8 }}>
        {runs.map((r) => (
          <div
            key={r.id}
            style={{
              display: "flex",
              gap: 12,
              alignItems: "baseline",
              flexWrap: "wrap",
              fontSize: "var(--fs-sm)",
              border: "1px solid var(--color-divider)",
              borderRadius: 8,
              padding: "8px 12px",
            }}
          >
            <strong>#{r.id}</strong>
            <span style={{ color: "var(--color-muted)" }}>{when(r.started_at)}</span>
            <span style={{ marginLeft: "auto", display: "flex", gap: 10 }}>
              <span>{r.added} added</span>
              <span>{r.updated} updated</span>
              <span>{r.matched} current</span>
              <span style={{ color: r.queued ? "var(--color-accent-900)" : undefined }}>
                {r.queued} queued
              </span>
              <span style={{ color: r.failed ? "var(--color-bad)" : undefined }}>{r.failed} failed</span>
              <span style={{ color: "var(--color-muted)" }}>{r.refused} refused</span>
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
