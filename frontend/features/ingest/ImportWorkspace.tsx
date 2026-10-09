"use client";

import { useState, type ReactNode } from "react";
import { useAgentChat } from "@/lib/useAgentChat";
import { CoverageChart } from "./components/CoverageChart";
import { Milestones } from "./components/Milestones";
import { RunStatus } from "./components/RunStatus";
import { PausedPick } from "./components/SourcePicker";
import { SaveQuestions } from "./components/SaveQuestions";
import { StartStep } from "./components/StartStep";
import { StepBar } from "./components/StepBar";
import { SubagentBoard } from "./components/SubagentBoard";
import { failuresOf } from "./lib/failures";

/** One Import conversation. `onStartOver` hands the parent a fresh thread; `start` shows below the Start step. */
export function ImportWorkspace({
  threadId,
  onStartOver,
  start,
}: {
  threadId: string;
  onStartOver: () => void;
  start?: ReactNode;
}) {
  const { turns, send, stop, isRunning, isReady } = useAgentChat(threadId, "sangam_ingest", "sangam-import");
  const [draft, setDraft] = useState("");
  // The chat stays for anything the task cards don't cover.
  const [advanced, setAdvanced] = useState(false);
  const atStart = turns.length === 0;
  const lastSteps = turns.length > 0 ? (turns[turns.length - 1]?.steps ?? []) : [];

  async function submit(text: string) {
    const value = text.trim();
    if (!value || isRunning) return;
    setDraft("");
    await send(value);
  }

  function startOver() {
    if (isRunning && !window.confirm("Stop the run and start over? Research already saved is kept.")) return;
    if (isRunning) stop();
    onStartOver();
  }

  return (
    <div className="import-ws">
      <StepBar current={atStart ? 0 : 1} />
      {atStart && !advanced && (
        <>
          <StartStep onStart={(prompt) => void submit(prompt)} disabled={!isReady} />
          <button type="button" className="import-link import-advanced" onClick={() => setAdvanced(true)}>
            Advanced: type your own request
          </button>
        </>
      )}

      <div className="import-turns">
        {turns.map((turn) => (
          <article key={turn.id} className="import-turn">
            <p className="import-question">{turn.question}</p>

            {/* The stages of the run, above the step-by-step. A reader wants
                to know what was reached before they want to know how. */}
            <Milestones steps={turn.steps} running={turn.streaming} />

            {/* Subagents get their own board: several run at once and a flat
                list of "Delegating a sub-task" hides that entirely. */}
            <SubagentBoard steps={turn.steps.filter((s) => s.tool === "task")} />

            {turn.steps
              .filter((s) => s.tool === "coverage_report" && s.result)
              .map((s) => (
                <CoverageChart key={s.id} text={s.result} />
              ))}

            {/* Refusals and failures only. The findings belong in the answer and
                the stages belong above; a line per tool call buried both. */}
            {failuresOf(turn.steps).map((f) => (
              <div key={f.id} className="import-failure">
                <span className="import-failure-label">{f.label}</span>
                <span className="muted">{f.detail}</span>
                <span className="import-failure-note">{f.note}</span>
                {f.count > 1 && <span className="save-note">×{f.count}</span>}
              </div>
            ))}

            {turn.answer && <div className="import-answer">{turn.answer}</div>}
          </article>
        ))}
      </div>

      {/* Mounted once the thread's agent is registered: useInterrupt looks it up by id. */}
      {isReady && <PausedPick agentId={`sangam-import-${threadId}`} steps={lastSteps} />}
      {isReady && <SaveQuestions agentId={`sangam-import-${threadId}`} />}

      <RunStatus running={isRunning} steps={lastSteps} />

      {(!atStart || advanced) && (
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit(draft);
        }}
        className="import-form"
      >
        <input
          className="input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={isReady ? "Ask Sangam Import to run or explain a source…" : "Connecting…"}
          disabled={!isReady}
        />
        {isRunning ? (
          <button type="button" className="btn btn-primary" onClick={stop}>
            Stop
          </button>
        ) : (
          <button type="submit" className="btn btn-primary" disabled={!isReady}>
            Send
          </button>
        )}
        {turns.length > 0 && (
          <button type="button" className="btn btn-ghost" onClick={startOver}>
            Start over
          </button>
        )}
      </form>
      )}
      {atStart && start}
    </div>
  );
}
