"use client";

import { useMemo, useState } from "react";
import { useAgentChat } from "@/lib/useAgentChat";
import { RunStatus } from "./components/RunStatus";
import { SubagentBoard } from "./components/SubagentBoard";
import { HIDDEN_TOOLS, humanizeTool, stepNote } from "./lib/toolLabels";

const SUGGESTIONS = [
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

            {/* Subagents get their own board: several run at once and a flat
                list of "Delegating a sub-task" hides that entirely. */}
            <SubagentBoard steps={turn.steps.filter((s) => s.tool === "task")} />

            {turn.steps
              .filter((step) => !HIDDEN_TOOLS.has(step.tool) && step.tool !== "task")
              .map((step) => {
                const { label, detail } = humanizeTool(step.tool);
                const note = stepNote(step.result);
                return (
                  <div
                    key={step.id}
                    style={{
                      borderLeft: "3px solid var(--color-divider)",
                      paddingLeft: 12,
                      fontSize: "var(--fs-sm)",
                    }}
                  >
                    <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                      <span style={{ fontWeight: 600 }}>{label}</span>
                      <span style={{ color: "var(--color-muted)" }}>{detail(step.args)}</span>
                      {step.running && <span style={{ color: "var(--color-muted)" }}>…</span>}
                    </div>
                    {/* The findings belong in the answer, not the trace. Only a
                        refusal or an error is surfaced here, because those change
                        what the answer can claim. */}
                    {note && (
                      <div style={{ color: "var(--color-bad)", fontSize: "var(--fs-xs)", marginTop: 2 }}>
                        {note}
                      </div>
                    )}
                  </div>
                );
              })}

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
