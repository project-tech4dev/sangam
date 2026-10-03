"use client";

import { useMemo, useState } from "react";
import { useAgentChat } from "@/lib/useAgentChat";
import { Milestones } from "./components/Milestones";
import { RunStatus } from "./components/RunStatus";
import { SubagentBoard } from "./components/SubagentBoard";
import { failuresOf } from "./lib/failures";

const SUGGESTIONS = [
  // Loads the funder-scan skill, which supplies the 28-field brief so nobody
  // has to paste it.
  "Funding profile for SBI Foundation and Infosys Foundation",
  "Which sources can you read, and which are held back?",
  "Run an import from India CSR, 5 articles",
  "Summarise the last run",
  "What is waiting for review?",
];

export function ImportWorkspace() {
  const threadId = useMemo(() => `import-${crypto.randomUUID()}`, []);
  const { turns, send, isRunning, isReady } = useAgentChat(threadId, "sangam_ingest", "sangam-import");
  const [draft, setDraft] = useState("");

  async function submit(text: string) {
    const value = text.trim();
    if (!value || isRunning) return;
    setDraft("");
    await send(value);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, minHeight: 420 }}>
      <div style={{ display: "grid", gap: 18 }}>
        {turns.length === 0 && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                className="btn"
                style={{ fontSize: "var(--fs-sm)" }}
                onClick={() => submit(s)}
                disabled={!isReady}
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {turns.map((turn) => (
          <article key={turn.id} style={{ display: "grid", gap: 10 }}>
            <p style={{ fontWeight: 700, margin: 0 }}>{turn.question}</p>

            {/* The stages of the run, above the step-by-step. A reader wants
                to know what was reached before they want to know how. */}
            <Milestones steps={turn.steps} running={turn.streaming} />

            {/* Subagents get their own board: several run at once and a flat
                list of "Delegating a sub-task" hides that entirely. */}
            <SubagentBoard steps={turn.steps.filter((s) => s.tool === "task")} />

            {/* Refusals and failures only. The findings belong in the answer and
                the stages belong above; a line per tool call buried both. */}
            {failuresOf(turn.steps).map((f) => (
              <div
                key={f.id}
                style={{
                  borderLeft: "3px solid var(--color-bad)",
                  paddingLeft: 12,
                  fontSize: "var(--fs-sm)",
                }}
              >
                <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                  <span style={{ fontWeight: 600 }}>{f.label}</span>
                  <span style={{ color: "var(--color-muted)" }}>{f.detail}</span>
                  <span style={{ color: "var(--color-bad)", fontSize: "var(--fs-xs)" }}>
                    {f.note}
                  </span>
                  {f.count > 1 && (
                    <span style={{ color: "var(--color-muted)", fontSize: "var(--fs-xs)" }}>
                      ×{f.count}
                    </span>
                  )}
                </div>
              </div>
            ))}

            {turn.answer && (
              <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{turn.answer}</div>
            )}
          </article>
        ))}
      </div>

      <RunStatus
        running={isRunning}
        steps={turns.length > 0 ? (turns[turns.length - 1]?.steps ?? []) : []}
      />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit(draft);
        }}
        style={{ display: "flex", gap: 8, marginTop: "auto" }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={isReady ? "Ask Sangam Import to run or explain a source…" : "Connecting…"}
          disabled={!isReady}
          style={{
            flex: 1,
            padding: "10px 14px",
            borderRadius: 10,
            border: "1px solid var(--color-divider)",
            fontSize: "var(--fs-md)",
          }}
        />
        <button type="submit" className="btn btn-primary" disabled={!isReady || isRunning}>
          {isRunning ? "Running…" : "Send"}
        </button>
      </form>
    </div>
  );
}
