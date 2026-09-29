"use client";

import { useEffect, useState } from "react";
import type { TraceStep } from "@/lib/useAgentChat";

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
    setStartedAt(running ? Date.now() : null);
  }, [running]);

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [running]);

  if (!running) return null;

  const researchers = steps.filter((s) => s.tool === "task");
  const active = steps.filter((s) => s.running);
  const current = active[active.length - 1];
  const doing = current
    ? current.tool.replace(/_/g, " ")
    : steps.length === 0
      ? "thinking"
      : "deciding what to do next";

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
        style={{
          width: 9,
          height: 9,
          borderRadius: "50%",
          background: "var(--color-accent-900)",
          animation: "sangamPulse 1.1s ease-in-out infinite",
          flexShrink: 0,
        }}
      />
      <span style={{ fontWeight: 600 }}>Running</span>
      <span style={{ color: "var(--color-muted)" }}>{doing}</span>
      <span style={{ marginLeft: "auto", color: "var(--color-muted)", fontSize: "var(--fs-xs)" }}>
        {steps.length} step{steps.length === 1 ? "" : "s"}
        {researchers.length > 0 &&
          ` · ${researchers.filter((r) => r.running).length}/${researchers.length} researchers`}
        {startedAt !== null && ` · ${elapsed(startedAt)}`}
      </span>
    </div>
  );
}
