"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useAgentContext } from "@copilotkit/react-core/v2";
import { useAgentChat, type TraceStep } from "@/lib/useAgentChat";
import { DoneReport } from "./components/DoneReport";
import { SaveQuestions } from "./components/SaveQuestions";
import { ScoutRail, type StaffPanels } from "./components/ScoutRail";
import { ScoutReply } from "./components/ScoutReply";
import { ScoutRunPanel } from "./components/ScoutRunPanel";
import { SourcePicker } from "./components/SourcePicker";
import { SourcesCard } from "./components/SourcesCard";
import { WorkingBoard } from "./components/WorkingBoard";
import { tasksFor, type ImportAccess, type VaultFile } from "./lib/access";
import { leadIn, type ImportTask } from "./lib/composePrompt";
import { boardOf } from "./lib/board";
import { slugsOf } from "./lib/done";
import { failuresOf } from "./lib/failures";
import { EMPTY_SOURCES, nothingChosen, readingFrom, type SourcesChoice } from "./lib/sourcePick";
import { fetchImportMessages } from "./lib/threads";

// The backend's TickedSources looks this description up, so the supervisor's first reply does not ask again.
function TickedSources({ choice }: { choice: SourcesChoice }) {
  useAgentContext({ description: "Sources the person ticked for this Import run", value: choice });
  return null;
}

// Reading a workbook or a Doc Vault, or a news import: data is being pulled even with no organisation rows yet.
const pulls = (s: TraceStep) =>
  s.tool === "run_import_now" ||
  (s.tool === "task" && ["workbook-reader", "vault-reader"].includes((s.args as { subagent_type?: string })?.subagent_type ?? ""));

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

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
  // When the first request went, so Done shows only names this run queued.
  const [since, setSince] = useState<number | null>(null);
  // The open question is the Review card, as opposed to the sources one.
  const [reviewing, setReviewing] = useState(false);
  // A review was answered, so what runs now is the save: the step bar stays on Done.
  const [reviewed, setReviewed] = useState(false);
  // From the Done cards: organisations still waiting for a review, and how many were saved.
  const [counts, setCounts] = useState({ pending: 0, saved: 0 });
  // Stable, because PauseSignal re-runs its effect whenever this changes.
  const onReview = useCallback((open: boolean) => {
    setPaused(open);
    setReviewing(open);
    if (open) setReviewed(true);
  }, []);
  // The run shown in the pinned panel; null follows the latest one.
  const [pinned, setPinned] = useState<string | null>(null);
  // Opened or closed by hand on this step; otherwise the panel is open only while Working.
  const [opened, setOpened] = useState<{ step: number; open: boolean } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Follow new text only while the person is at the bottom; scrolling up to read stops the follow.
  const following = useRef(true);
  // A sent message glides into view; streamed text follows instantly, since a glide per token stutters.
  const glideUntil = useRef(0);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const atStart = turns.length === 0 && !isLoadingHistory;
  const needsSources = atStart && task !== null && task !== "news";
  const lastSteps = turns[turns.length - 1]?.steps ?? [];

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !following.current) return;
    if (glideUntil.current > Date.now()) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    else el.scrollTop = el.scrollHeight;
  }, [turns, paused]);

  // A follow-up box starts at one line and grows with the text, up to its CSS max-height.
  useEffect(() => {
    const el = inputRef.current;
    if (!el || atStart) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [draft, atStart]);

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
    setPinned(null);
    setOpened(null);
    following.current = true;
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) glideUntil.current = Date.now() + 500;
    setReviewed(false);
    setCounts({ pending: 0, saved: 0 });
    setSince((prev) => prev ?? Date.now());
    await send(value);
  }

  function startOver() {
    if (isRunning && !window.confirm("Stop the run and start a new chat? Research already saved is kept.")) return;
    if (isRunning) stop();
    onStartOver();
  }

  const composer = (
    <div className={atStart ? "card elev-sm composer" : "card elev-sm composer is-compact"}>
      <textarea
        ref={inputRef}
        rows={atStart ? undefined : 1}
        className="input composer-input"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void submit();
          }
        }}
        placeholder={atStart ? "Pick a task above, or tell Scout what to find out…" : "Ask Scout a follow-up…  ⌘↵ to send"}
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
  const ticked = preset ?? (needsSources ? sources : null);
  const questions = isReady && (
    <>
      {ticked && <TickedSources choice={ticked} />}
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

  // Turns that researched organisations, with how many: they get a marker in the thread and the pinned panel.
  const runs = new Map<string, number>();
  for (const t of turns) {
    const n = boardOf(t.steps, t.streaming, laneOwners, false).rows.length;
    if (n > 0 || t.steps.some(pulls)) runs.set(t.id, n);
  }
  const runTurnId = pinned && runs.has(pinned) ? pinned : [...runs.keys()].at(-1);
  const runTurn = turns.find((t) => t.id === runTurnId);
  const run = runTurn && (() => {
    const waiting = paused && runTurn === turns[turns.length - 1];
    return {
      turn: runTurn,
      waiting,
      done: !runTurn.streaming && !waiting && slugsOf(runTurn.steps).length > 0,
      board: (
        <WorkingBoard steps={runTurn.steps} running={runTurn.streaming} paused={waiting} laneOwners={laneOwners} compact />
      ),
    };
  })();

  // The steps only mean something once Scout has started pulling data; before that the thread is plain chat.
  const step = isRunning
    ? reviewed
      ? 2
      : 1
    : reviewing || counts.pending > 0
      ? 2
      : counts.saved > 0 || (run && slugsOf(run.turn.steps).length === 0)
        ? 3
        : 2;
  const panelOpen = opened && opened.step === step ? opened.open : step === 1;
  const count = run ? (runs.get(run.turn.id) ?? 0) : 0;
  const ready = run ? boardOf(run.turn.steps, run.turn.streaming, laneOwners, run.waiting).ready : 0;
  const status =
    run && run.turn.streaming && !run.done
      ? count > 0
        ? `${ready} of ${plural(count, "organisation")} ready`
        : "Scout is reading…"
      : count > 0
        ? `Researched ${plural(count, "organisation")}`
        : "Reading finished";
  const action = step === 2 ? (counts.pending > 0 ? `Review ${counts.pending} →` : "Review →") : step === 1 ? "Show progress" : "Show";

  return (
    <>
      {atStart ? (
        <div className="chat-pane is-empty scout-empty">
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
          {run && (
          <ScoutRunPanel
            step={step}
            status={status}
            action={action}
            live={isRunning}
            open={panelOpen}
            onToggle={() => setOpened({ step, open: !panelOpen })}
            tall={step !== 1}
          >
            {run &&
              (run.done ? (
                <DoneReport
                  slugs={slugsOf(run.turn.steps)}
                  since={since}
                  onStartOver={startOver}
                  onCounts={setCounts}
                  fallback={run.board}
                  compact
                />
              ) : (
                run.board
              ))}
          </ScoutRunPanel>
          )}
          <div
            ref={scrollRef}
            className="chat-scroll scout-thread"
            onScroll={(e) => {
              const el = e.currentTarget;
              if (glideUntil.current > Date.now()) return;
              following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
            }}
          >
            {isLoadingHistory && <p className="muted">Opening this chat…</p>}
            <div className="chat-turns">
              {turns.map((turn, i) => {
                const count = runs.get(turn.id);
                const shown = run?.turn.id === turn.id;
                return (
                  <article key={turn.id} className="chat-turn">
                    <div className="chat-question">
                      <span className="chat-you">You</span>
                      <span className="chat-question-text">{turn.question}</span>
                    </div>
                    {turn.answer && <ScoutReply text={turn.answer} />}
                    {count !== undefined && (
                      <button
                        type="button"
                        className="scout-run-marker"
                        onClick={() => {
                          setPinned(i === turns.length - 1 ? null : turn.id);
                          setOpened({ step, open: true });
                        }}
                      >
                        {count > 0
                          ? `${turn.streaming ? "Researching" : "Researched"} ${plural(count, "organisation")}`
                          : turn.streaming
                            ? "Reading your files"
                            : "Read your files"}
                        <span className="muted">{shown ? " · shown above" : " · show above"}</span>
                      </button>
                    )}
                    {/* Refusals and failures only; the findings belong in the reply. */}
                    {failuresOf(turn.steps).map((f) => (
                      <div key={f.id} className="import-failure">
                        <span className="import-failure-label">{f.label}</span>
                        <span className="muted">{f.detail}</span>
                        <span className="import-failure-note">{f.note}</span>
                        {f.count > 1 && <span className="review-note">×{f.count}</span>}
                      </div>
                    ))}
                  </article>
                );
              })}
              {/* The questions Scout stops on belong to the last turn. */}
              {questions}
            </div>
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
