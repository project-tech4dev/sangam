import type { ResearchRecord } from "../lib/types";

const TONE: Record<string, string> = {
  complete: "var(--color-accent-2-900)",
  partial: "var(--color-accent-900)",
  not_found: "var(--color-muted)",
  wrong_entity: "var(--color-bad)",
};

/**
 * What the researchers have actually saved. Without this the only evidence a
 * run produced anything was a chat message that scrolls away, which is why
 * saved research kept looking like lost research.
 */
export function ResearchShelf({ items }: { items: ResearchRecord[] }) {
  if (items.length === 0) return null;
  const facts = items.reduce((n, r) => n + r.fact_count, 0);
  return (
    <section>
      <h2 style={{ fontSize: "var(--fs-lg)", margin: "0 0 4px" }}>Research on file</h2>
      <p style={{ fontSize: "var(--fs-sm)", color: "var(--color-muted)", margin: "0 0 12px" }}>
        {items.length} organisation{items.length === 1 ? "" : "s"}, {facts} facts, each with the
        sentence behind it. Run <code>make client-docs</code> to write these to{" "}
        <code>docs/entities/</code>.
      </p>
      <div style={{ display: "grid", gap: 8 }}>
        {items.map((r) => (
          <article
            key={r.id}
            style={{
              border: "1px solid var(--color-divider)",
              borderLeft: `3px solid ${TONE[r.status] ?? "var(--color-divider)"}`,
              borderRadius: 8,
              padding: "9px 12px",
            }}
          >
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
              <strong style={{ fontSize: "var(--fs-sm)" }}>
                {r.canonical_name ?? r.entity_name}
              </strong>
              <span style={{ fontSize: "var(--fs-xs)", color: TONE[r.status] }}>{r.status}</span>
              <span
                style={{
                  marginLeft: "auto",
                  fontSize: "var(--fs-xs)",
                  color: "var(--color-muted)",
                }}
              >
                {r.fact_count} facts · {r.sources_read.length} sources
              </span>
            </div>
            <p
              style={{
                margin: "5px 0 0",
                fontSize: "var(--fs-xs)",
                color: "var(--color-muted)",
                lineHeight: 1.45,
              }}
            >
              {r.summary.slice(0, 190)}
              {r.summary.length > 190 ? "…" : ""}
            </p>
            {r.stopped_reason && (
              <p style={{ margin: "4px 0 0", fontSize: "var(--fs-xs)", color: TONE.partial }}>
                stopped: {r.stopped_reason}
              </p>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
