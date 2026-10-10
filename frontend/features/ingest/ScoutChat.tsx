"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useAgentChat } from "@/lib/useAgentChat";
import { AgentNotes } from "./components/AgentNotes";
import { DoneReport } from "./components/DoneReport";
import { SaveQuestions } from "./components/SaveQuestions";
import { ScoutRail, type StaffPanels } from "./components/ScoutRail";
import { SourcePicker } from "./components/SourcePicker";
import { SourcesCard } from "./components/SourcesCard";
import { WorkingBoard } from "./components/WorkingBoard";
import { tasksFor, type ImportAccess, type VaultFile } from "./lib/access";
import { leadIn, type ImportTask } from "./lib/composePrompt";
import { slugsOf } from "./lib/done";
import { failuresOf } from "./lib/failures";
import { EMPTY_SOURCES, nothingChosen, readingFrom, type SourcesChoice } from "./lib/sourcePick";
import { fetchImportMessages } from "./lib/threads";

const TASKS: { id: ImportTask; title: string; desc: string }[] = [
  { id: "funder", title: "Research a funder", desc: "How to apply, who is eligible, and which documents they want." },
  { id: "ngo", title: "Check an NGO", desc: "Is it ready for CSR money — registrations, accounts and track record." },
  { id: "news", title: "Get the latest CSR news", desc: "Read recent articles and update the funders Sangam already knows." },
];

/** One Scout thread: task cards over the composer, then every turn — working, review, done — in one chat. */
export function ScoutChat({
  threadId,
  resume = false,
  onStartOver,
  onFirstSend,
  below,
  access,
  vaultFiles = [],
  staff,
}: {
  threadId: string;
  /** Load the thread's saved messages: it was opened from the list. */
  resume?: boolean;
  onStartOver: () => void;
  /** The thread's first request, so the parent can list it and put it in the URL. */
  onFirstSend?: (text: string) => void;
  /** Shown under the empty composer: what was researched, and the team's source details. */
  below?: ReactNode;
  access: ImportAccess;
  /** The person's organisations' private files, offered for reading before the web. */
  vaultFiles?: VaultFile[];
  staff: StaffPanels | null;
}) {
  const load = useCallback(() => fetchImportMessages(threadId), [threadId]);
  const { turns, send, stop, isRunning, isReady, isLoadingHistory, laneOwners } = useAgentChat(
    threadId,
    "sangam_ingest",
    "sangam-import",
    resume ? load : undefined,
  );
  const [draft, setDraft] = useState("");
  const [task, setTask] = useState<ImportTask | null>(null);
  const [sources, setSources] = useState<SourcesChoice>(EMPTY_SOURCES);
  // What was ticked before the first message; it answers the run's sources pause so no card asks again.
  const [preset, setPreset] = useState<SourcesChoice | null>(null);
  // A question card is open: the run has stopped to wait for an answer, not finished.
  const [paused, setPaused] = useState(false);
  // The open question is the Review card, as opposed to the sources one.
  const [reviewing, setReviewing] = useState(false);
  // When the first request went, so Done shows only names this run queued.
  const [since, setSince] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Stable, because PauseSignal re-runs its effect whenever this changes.
  const onReview = useCallback((open: boolean) => {
    setPaused(open);
    setReviewing(open);
  }, []);

  const atStart = turns.length === 0 && !isLoadingHistory;
  const needsSources = atStart && task !== null && task !== "news";
  const lastSteps = turns[turns.length - 1]?.steps ?? [];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [turns, paused]);

  function pickTask(next: ImportTask) {
    setTask(next);
    setDraft(leadIn(next));
  }

  async function submit() {
    const value = draft.trim();
    if (!value || isRunning || (needsSources && nothingChosen(sources))) return;
    if (atStart) {
      setPreset(needsSources ? sources : null);
      onFirstSend?.(value);
    }
    setDraft("");
    setSince((prev) => prev ?? Date.now());
    await send(value);
  }

  function startOver() {
    if (isRunning && !window.confirm("Stop the run and start a new chat? Research already saved is kept.")) return;
    if (isRunning) stop();
    onStartOver();
  }

  const composer = (
    <div className="card elev-sm composer">
      <textarea
        className="input composer-input"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void submit();
          }
        }}
        placeholder={atStart ? "Pick a task above, or tell Scout what to find out…" : "Ask Scout a follow-up…"}
        aria-label="Message Scout"
        disabled={!isReady}
      />
      <div className="composer-row">
        <span className="composer-hint muted">
          {!isReady
            ? "Connecting to Scout…"
            : needsSources && nothingChosen(sources)
              ? "Choose where Scout reads from first."
              : "⌘↵ to send"}
        </span>
        <div className="composer-actions">
          {turns.length > 0 && (
            <button type="button" className="btn btn-ghost" onClick={startOver}>
              New chat
            </button>
          )}
          {isRunning ? (
            <button type="button" className="btn btn-primary" onClick={stop}>
              Stop
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void submit()}
              disabled={!isReady || !draft.trim() || (needsSources && nothingChosen(sources))}
            >
              Send to Scout
            </button>
          )}
        </div>
      </div>
    </div>
  );

  // Mounted once the agent is registered (useInterrupt looks it up by id), and in both layouts, so no pause is missed.
  const questions = isReady && (
    <>
      <SourcesCard
        agentId={`sangam-import-${threadId}`}
        access={access}
        vaultFiles={vaultFiles}
        preset={preset}
        onPaused={setPaused}
      />
      <SaveQuestions agentId={`sangam-import-${threadId}`} onPaused={onReview} />
    </>
  );

  const picker = (
    <SourcePicker
      value={sources}
      onChange={setSources}
      staff={access.staff}
      vaultFiles={vaultFiles}
      showOrg={access.orgs.length > 1}
    />
  );

  return (
    <>
      {atStart ? (
        <div className="chat-pane is-empty">
          <h2 className="chat-empty-title">What should Scout find out?</h2>
          <div role="radiogroup" aria-label="Task" className="import-tasks scout-task-row">
            {TASKS.filter((t) => tasksFor(access).includes(t.id)).map((t) => (
              <button
                key={t.id}
                type="button"
                role="radio"
                aria-checked={task === t.id}
                className="import-task"
                onClick={() => pickTask(t.id)}
              >
                <span className="import-task-title">
                  <span className="import-task-radio" />
                  {t.title}
                </span>
                <span className="import-task-desc">{t.desc}</span>
              </button>
            ))}
          </div>
          {composer}
          {/* Narrow screens hide the rail, so the sources come up here instead. */}
          {needsSources && <div className="scout-sources-inline">{picker}</div>}
          {questions}
          {below}
        </div>
      ) : (
        <div className="chat-pane">
          <div className="chat-scroll">
            {isLoadingHistory && <p className="muted">Opening this chat…</p>}
            <div className="chat-turns">
              {turns.map((turn, i) => {
                const last = i === turns.length - 1;
                const waiting = paused && last;
                const board = (
                  <WorkingBoard steps={turn.steps} running={turn.streaming} paused={waiting} laneOwners={laneOwners} />
                );
                const slugs = slugsOf(turn.steps);
                const done = !turn.streaming && !waiting && slugs.length > 0;
                return (
                  <article key={turn.id} className="chat-turn">
                    <div className="chat-question">
                      <span className="chat-you">You</span>
                      <span className="chat-question-text">{turn.question}</span>
                    </div>
                    {done ? (
                      <DoneReport slugs={slugs} since={since} onStartOver={startOver} fallback={board} />
                    ) : waiting && reviewing ? null : (
                      board
                    )}
                    {/* Refusals and failures only; the findings belong in the notes. */}
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
              {/* The questions Scout stops on belong to the last turn. */}
              {questions}
            </div>
            <div ref={bottomRef} />
          </div>
          {composer}
        </div>
      )}
      <div className="evidence-rail-slot">
        <ScoutRail
          started={!atStart}
          task={task}
          sources={sources}
          onSources={setSources}
          readFrom={readingFrom(lastSteps)}
          access={access}
          vaultFiles={vaultFiles}
          staff={staff}
        />
      </div>
    </>
  );
}
