"use client";

import { useState } from "react";

/** One of LangChain's HumanInTheLoopMiddleware decisions; the run resumes with `{decisions: [it]}`. */
export type PickDecision =
  | { type: "approve" }
  | { type: "edit"; edited_action: { name: string; args: { paths: string[] } } }
  | { type: "reject"; message: string };

/**
 * The run is paused on select_source_files. Staff tick the workbooks it may read:
 * the agent's proposal comes pre-ticked, and every file it listed can be added.
 */
export function SourcePicker({
  proposed,
  listed,
  onDecide,
}: {
  proposed: string[];
  listed: string[];
  onDecide: (decision: PickDecision) => void;
}) {
  const options = Array.from(new Set([...proposed, ...listed]));
  const [ticked, setTicked] = useState<Set<string>>(() => new Set(proposed));
  const [sent, setSent] = useState(false);

  function toggle(path: string) {
    setTicked((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  function decide(decision: PickDecision) {
    setSent(true);
    onDecide(decision);
  }

  function confirm() {
    const paths = options.filter((p) => ticked.has(p));
    const unchanged = paths.length === proposed.length && proposed.every((p) => ticked.has(p));
    decide(
      unchanged
        ? { type: "approve" }
        : { type: "edit", edited_action: { name: "select_source_files", args: { paths } } },
    );
  }

  return (
    <section
      aria-label="Choose staff workbooks"
      style={{
        border: "1px solid var(--color-divider)",
        borderRadius: "var(--radius-surface)",
        background: "var(--color-surface)",
        padding: 16,
        display: "grid",
        gap: 12,
      }}
    >
      <div style={{ display: "grid", gap: 4 }}>
        <strong>Which staff workbooks should this run read?</strong>
        <span style={{ color: "var(--color-muted)", fontSize: "var(--fs-sm)" }}>
          The run is paused until you confirm. Ticked files are read by every researcher.
        </span>
      </div>

      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 6 }}>
        {options.map((path) => (
          <li key={path}>
            <label
              style={{ display: "flex", gap: 8, alignItems: "center", fontSize: "var(--fs-sm)" }}
            >
              <input
                type="checkbox"
                checked={ticked.has(path)}
                onChange={() => toggle(path)}
                disabled={sent}
              />
              <span style={{ wordBreak: "break-all" }}>{path.replace(/^staff-sources\//, "")}</span>
              {proposed.includes(path) && (
                <span style={{ color: "var(--color-muted)", fontSize: "var(--fs-xs)" }}>
                  suggested
                </span>
              )}
            </label>
          </li>
        ))}
      </ul>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button
          type="button"
          className="btn btn-primary"
          onClick={confirm}
          disabled={sent || ticked.size === 0}
        >
          Read {ticked.size} {ticked.size === 1 ? "file" : "files"}
        </button>
        <button
          type="button"
          className="btn"
          onClick={() =>
            decide({ type: "reject", message: "Staff chose not to use any staff workbook for this run." })
          }
          disabled={sent}
        >
          Continue without staff data
        </button>
      </div>
    </section>
  );
}
