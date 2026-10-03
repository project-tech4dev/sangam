"use client";

import { useEffect, useState } from "react";
import type { TraceStep } from "@/lib/useAgentChat";
import { humanizeTool } from "../lib/toolLabels";

/** The same label the trace uses — the raw tool name leaked out of here. */
function doing(current: TraceStep | undefined, stepCount: number): string {
  if (!current) return stepCount === 0 ? "thinking" : "deciding what to do next";
  const { label, detail } = humanizeTool(current.tool);
  return [label, detail(current.args)].filter(Boolean).join(" ");
}

function elapsed(sinceMs: number): string {
  const s = Math.floor((Date.now() - sinceMs) / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

/**
 * A run can spend minutes inside one tool call with nothing new on screen.
 * This is the "it is still alive" line: what it is doing, for how long.
 */
export function RunStatus({ running, steps }: { running: boolean; steps: TraceStep[] }) {
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [, tick] = useState(0);

  useEffect(() => {
    if (running) setStartedAt(Date.now());
  }, [running]);

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [running]);

  // Not `return null` when the run ends: the last thing a person wants to see
  // is what it did, and the indicator taking the tally with it is why a
  // finished run looked like nothing had happened.
  const finished = !running && steps.length > 0;
  if (!running && !finished) return null;

  // Two kinds of task now. Counting a writer as a researcher would report
  // "4/2 researchers" once the writers start.
  const tasks = steps.filter((s) => s.tool === "task");
  const researchers = tasks.filter((s) => (s.args as any)?.subagent_type !== "catalog-writer");
  const writers = tasks.filter((s) => (s.args as any)?.subagent_type === "catalog-writer");
  const active = steps.filter((s) => s.running);
  const current = active[active.length - 1];

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "9px 13px",
        border: "1px solid var(--color-divider)",
        borderRadius: 999,
        background: "var(--color-surface)",
        fontSize: "var(--fs-sm)",
      }}
    >
      <span
        aria-hidden
        className={running ? "sangam-pulse" : undefined}
        style={{
          width: 9,
          height: 9,
          borderRadius: "50%",
          background: running ? "var(--color-accent-900)" : "var(--color-accent-2-900)",
          flexShrink: 0,
        }}
      />
      <span style={{ fontWeight: 600 }}>{running ? "Running" : "Finished"}</span>
      <span style={{ color: "var(--color-muted)" }}>
        {running ? doing(current, steps.length) : "nothing in flight"}
      </span>
      <span style={{ marginLeft: "auto", color: "var(--color-muted)", fontSize: "var(--fs-xs)" }}>
        {steps.length} step{steps.length === 1 ? "" : "s"}
        {researchers.length > 0 &&
          ` · ${researchers.filter((r) => r.result === null).length}/${researchers.length} researching`}
        {writers.length > 0 &&
          ` · ${writers.filter((w) => w.result === null).length}/${writers.length} writing`}
        {startedAt !== null && ` · ${elapsed(startedAt)}`}
      </span>
    </div>
  );
}
