import type { ImportSource } from "../lib/types";

/** The source registry in three groups a person can act on, behind one question. */
export function SourceGroups({ sources }: { sources: ImportSource[] }) {
  const reads = sources.filter((s) => s.has_adapter);
  const allowed = sources.filter((s) => s.dispatchable && !s.has_adapter);
  const barred = sources.filter((s) => !s.dispatchable);
  const examples = (list: ImportSource[]) => list.slice(0, 2).map((s) => s.name).join(", ");
  const groups = [
    { n: reads.length, title: "Sangam reads these", text: "Set up and allowed. Sangam can pull from them any time.", ex: examples(reads) },
    { n: allowed.length, title: "Allowed, not set up yet", text: "Their rules allow reading, but Sangam can't read them on its own yet.", ex: examples(allowed) },
    { n: barred.length, title: "Not allowed", text: "Their terms say no, so Sangam never opens them — even if asked.", ex: examples(barred) },
  ];
  return (
    <details className="import-section import-disclosure">
      <summary className="import-link">Which websites is Sangam allowed to read?</summary>
      <div className="import-groups">
        {groups.map((g) => (
          <div key={g.title} className="import-group">
            <span className="import-group-n">{g.n}</span>
            <strong className="import-group-title">{g.title}</strong>
            <span className="import-group-text">{g.text}</span>
            {g.ex && <span className="import-hint">e.g. {g.ex}</span>}
          </div>
        ))}
      </div>
    </details>
  );
}
