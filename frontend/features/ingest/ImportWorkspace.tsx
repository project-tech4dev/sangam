"use client";

import { useCallback, useState, type ReactNode } from "react";
import { useAgentChat } from "@/lib/useAgentChat";
import { AgentNotes } from "./components/AgentNotes";
import { DoneReport } from "./components/DoneReport";
import { SaveQuestions } from "./components/SaveQuestions";
import { SpreadsheetsCard } from "./components/SpreadsheetsCard";
import { StartStep } from "./components/StartStep";
import { StepBar } from "./components/StepBar";
import { WorkingBoard } from "./components/WorkingBoard";
import { slugsOf } from "./lib/done";
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
  const { turns, send, stop, isRunning, isReady, laneOwners } = useAgentChat(threadId, "sangam_ingest", "sangam-import");
  const [draft, setDraft] = useState("");
  // The chat stays for anything the task cards don't cover.
  const [advanced, setAdvanced] = useState(false);
  // A question card is open: the run has stopped to wait for an answer, not finished.
  const [paused, setPaused] = useState(false);
  // The open question is the Review card, as opposed to the spreadsheets one.
  const [reviewing, setReviewing] = useState(false);
  // A review was answered, so what runs now is the save: the step bar stays on Done.
  const [reviewed, setReviewed] = useState(false);
  // When the first request went, so Done shows only names this run queued.
  const [since, setSince] = useState<number | null>(null);
  // The first request came from the task cards, so it is Sangam's wording, not something to show back.
  const [guided, setGuided] = useState(false);
  // Stable, because PauseSignal re-runs its effect whenever this changes.
  const onReview = useCallback((open: boolean) => {
    setPaused(open);
    setReviewing(open);
    if (open) setReviewed(true);
  }, []);
  const atStart = turns.length === 0;
  const lastSteps = turns.length > 0 ? (turns[turns.length - 1]?.steps ?? []) : [];

  async function submit(text: string) {
    const value = text.trim();
    if (!value || isRunning) return;
    setDraft("");
    setSince((prev) => prev ?? Date.now());
    await send(value);
  }

  function startOver() {
    if (isRunning && !window.confirm("Stop the run and start over? Research already saved is kept.")) return;
    if (isRunning) stop();
    onStartOver();
  }

  return (
    <div className="import-ws">
      <StepBar current={atStart ? 0 : reviewing ? 2 : reviewed || (!isRunning && !paused) ? 3 : 1} />
      {atStart && !advanced && (
        <>
          <StartStep
            onStart={(prompt) => {
              setGuided(true);
              void submit(prompt);
            }}
            disabled={!isReady}
          />
          <button type="button" className="import-link import-advanced" onClick={() => setAdvanced(true)}>
            Advanced: type your own request
          </button>
        </>
      )}

      <div className="import-turns">
        {turns.map((turn, i) => {
          const waiting = paused && i === turns.length - 1;
          const board = <WorkingBoard steps={turn.steps} running={turn.streaming} paused={waiting} laneOwners={laneOwners} />;
          const slugs = slugsOf(turn.steps);
          const done = !turn.streaming && !waiting && slugs.length > 0;
          return (
            <article key={turn.id} className="import-turn">
              {!(guided && i === 0) && <p className="import-question">{turn.question}</p>}

              {done ? (
                <DoneReport
                  slugs={slugs}
                  since={since}
                  onStartOver={startOver}
                  onSave={(name) => void submit(`Save ${name} to Sangam`)}
                  busy={isRunning}
                  fallback={board}
                />
              ) : waiting && reviewing ? null : (
                board
              )}

              {/* Refusals and failures only. The findings belong in the answer and
                  the stages belong above; a line per tool call buried both. */}
              {failuresOf(turn.steps).map((f) => (
                <div key={f.id} className="import-failure">
                  <span className="import-failure-label">{f.label}</span>
                  <span className="muted">{f.detail}</span>
                  <span className="import-failure-note">{f.note}</span>
                  {f.count > 1 && <span className="review-note">×{f.count}</span>}
                </div>
              ))}

              {/* Keyed so the notes, open while they stream, start closed once Done shows. */}
              {turn.answer && <AgentNotes key={String(done)} text={turn.answer} collapsed={done} />}
            </article>
          );
        })}
      </div>

      {/* Mounted once the thread's agent is registered: useInterrupt looks it up by id. */}
      {isReady && <SpreadsheetsCard agentId={`sangam-import-${threadId}`} steps={lastSteps} turnId={turns.at(-1)?.id} onPaused={setPaused} />}
      {isReady && (
        <SaveQuestions agentId={`sangam-import-${threadId}`} onPaused={onReview} />
      )}

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
