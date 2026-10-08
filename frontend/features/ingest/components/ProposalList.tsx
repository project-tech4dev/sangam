import type { SourceProposal } from "../lib/types";

/** Hosts the importer read that nobody has classified. A note, never a permission. */
export function ProposalList({ items }: { items: SourceProposal[] }) {
  if (items.length === 0) return null;
  return (
    <section>
      <h2 style={{ fontSize: "var(--fs-lg)", margin: "0 0 4px" }}>Sources to classify</h2>
      <p style={{ fontSize: "var(--fs-sm)", color: "var(--color-muted)", margin: "0 0 12px" }}>
        Read because robots.txt allowed it, but not in the registry. Adding one to
        <code> app/ingest/data/sources</code> with its basis is what makes it a source.
      </p>
      <div style={{ display: "grid", gap: 8 }}>
        {items.map((p) => (
          <div
            key={p.id}
            style={{
              border: "1px solid var(--color-divider)",
              borderRadius: "var(--radius-surface)",
              padding: "8px 12px",
              fontSize: "var(--fs-sm)",
            }}
          >
            <strong>{p.host}</strong>
            <span style={{ color: "var(--color-muted)" }}>
              {" "}
              · {p.robots_result} · seen {p.times_seen}×
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
