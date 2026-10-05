"use client";

import { useState } from "react";
import { humanizeTool } from "../lib/toolLabels";
import type { TraceStep } from "../lib/useSangamChat";

/** The per-step activity log: what Sangam is doing, one line each. The high-level task,
 *  the sources and the SQL live in the rail, so nothing here is repeated there. */
export function TraceCard({ steps: visible, streaming }: { steps: TraceStep[]; streaming: boolean }) {
  const [open, setOpen] = useState(false);
  const expanded = streaming || open;
  if (visible.length === 0 && !streaming) return null;

  return (
    <div
      className="ask-in"
      style={{
        background: "var(--color-accent-2-100)",
        borderRadius: "var(--radius-surface)",
        padding: "12px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: "var(--fs-xs)", fontWeight: 600, color: "var(--color-accent-2-900)" }}>
          {streaming ? "Working…" : `How this answer was made — ${visible.length} step${visible.length === 1 ? "" : "s"}`}
        </span>
        {!streaming && visible.length > 0 && (
          <button
            className="btn btn-ghost"
            style={{ padding: 0, fontSize: "var(--fs-xs)", marginLeft: "auto" }}
            onClick={() => setOpen(!open)}
          >
            {open ? "Hide steps" : "Show steps"}
          </button>
        )}
      </div>
      {expanded &&
        visible.map((step) => {
          const label = humanizeTool(step.tool);
          return (
            <div key={step.id} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
              <span
                className={step.running ? "ask-pulse" : undefined}
                style={{
                  width: 20,
                  height: 20,
                  borderRadius: "50%",
                  flexShrink: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "var(--fs-xs)",
                  color: "#fff",
                  background: step.running ? "var(--color-accent-500)" : "var(--color-accent-2-600)",
                }}
              >
                {step.running ? "" : "✓"}
              </span>
              <div style={{ fontSize: "var(--fs-xs)" }}>
                <strong>{label.label}</strong>
                <span className="muted" style={{ marginLeft: 8, fontSize: "var(--fs-xs)" }}>
                  {label.detail(step.args)}
                </span>
              </div>
            </div>
          );
        })}
    </div>
  );
}
