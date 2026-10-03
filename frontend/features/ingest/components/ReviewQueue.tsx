import type { QueueItem } from "../lib/types";

/** Names the importer refused to merge on its own. */
export function ReviewQueue({ items }: { items: QueueItem[] }) {
  if (items.length === 0) return null;
  return (
    <section>
      <h2 style={{ fontSize: "var(--fs-lg)", margin: "0 0 4px" }}>Waiting for a person</h2>
      <p style={{ fontSize: "var(--fs-sm)", color: "var(--color-muted)", margin: "0 0 12px" }}>
        Each of these resembled an organisation already in the catalog — a funder or an NGO —
        without matching it. Merging two different organisations is the one mistake an import
        cannot undo, so it stops here.
      </p>
      <div style={{ display: "grid", gap: 8 }}>
        {items.map((q) => (
          <div
            key={q.id}
            style={{
              border: "1px solid var(--color-divider)",
              borderRadius: 8,
              padding: "10px 12px",
              fontSize: "var(--fs-sm)",
            }}
          >
            <strong>{q.raw_name}</strong>
            <span style={{ color: "var(--color-muted)" }}> · from {q.source}</span>
            <div style={{ marginTop: 6 }}>
              {q.candidates.length === 0 ? (
                <span style={{ color: "var(--color-muted)" }}>no candidate above the threshold</span>
              ) : (
                q.candidates.map((c) => (
                  <span key={c.id} style={{ marginRight: 12 }}>
                    {c.name} <span style={{ color: "var(--color-muted)" }}>({c.score})</span>
                  </span>
                ))
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
