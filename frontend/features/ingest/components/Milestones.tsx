"use client";

import type { TraceStep } from "@/lib/useAgentChat";
import { milestonesOf, type MilestoneState } from "../lib/milestones";

const TONE: Record<MilestoneState, string> = {
  pending: "var(--color-divider)",
  active: "var(--color-accent-900)",
  done: "var(--color-accent-2-900)",
  skipped: "var(--color-bad)",
};

const MARK: Record<MilestoneState, string> = {
  pending: "○",
  active: "◐",
  done: "✓",
  skipped: "✕",
};

/**
 * What the run has actually done, as stages rather than as forty tool calls.
 *
 * A stage it never reached is shown struck through in the bad tone, not
 * hidden: research that skipped the catalog is the failure a reader most
 * needs to see, and a trace of forty lines is where it used to disappear.
 */
export function Milestones({ steps, running }: { steps: TraceStep[]; running: boolean }) {
  const milestones = milestonesOf(steps, running);
  // Nothing has happened yet — an all-pending checklist is noise.
  if (milestones.every((m) => m.state === "pending")) return null;

  return (
    <section
      aria-label="What this run has done"
      style={{
        border: "1px solid var(--color-divider)",
        borderRadius: 10,
        padding: "10px 13px",
        background: "var(--color-surface)",
        display: "grid",
        gap: 7,
      }}
    >
      {milestones.map((m) => (
        <div key={m.key} style={{ display: "flex", gap: 9, alignItems: "baseline" }}>
          <span
            aria-hidden
            className={m.state === "active" ? "sangam-pulse" : undefined}
            style={{ color: TONE[m.state], fontSize: "var(--fs-sm)", width: 12, flexShrink: 0 }}
          >
            {MARK[m.state]}
          </span>
          <div style={{ minWidth: 0 }}>
            <span
              style={{
                fontSize: "var(--fs-sm)",
                fontWeight: m.state === "pending" ? 400 : 600,
                color: m.state === "pending" ? "var(--color-muted)" : "inherit",
              }}
            >
              {m.label}
            </span>{" "}
            <span
              style={{
                fontSize: "var(--fs-xs)",
                color: m.state === "skipped" ? "var(--color-bad)" : "var(--color-muted)",
              }}
            >
              {m.detail}
            </span>
            {m.items.length > 0 && (
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 3 }}>
                {m.items.slice(0, 12).map((item) => (
                  <span
                    key={item}
                    style={{
                      fontSize: "var(--fs-xs)",
                      color: "var(--color-muted)",
                      border: "1px solid var(--color-divider)",
                      borderRadius: 999,
                      padding: "1px 7px",
                    }}
                  >
                    {item}
                  </span>
                ))}
                {m.items.length > 12 && (
                  <span style={{ fontSize: "var(--fs-xs)", color: "var(--color-muted)" }}>
                    +{m.items.length - 12} more
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      ))}
    </section>
  );
}
