"use client";

import { useState } from "react";
import { EntityMark } from "@/components/ui/primitives";
import type { TraceStep } from "@/lib/useAgentChat";
import { boardOf, type BoardRow } from "../lib/board";
import { readingFrom } from "../lib/sourcePick";
import { humanizeTool } from "../lib/toolLabels";

/** The step in flight, for runs with no organisations to show (a news import) or none tied yet. */
function doing(steps: TraceStep[]): string {
  const current = steps.filter((s) => s.running).at(-1);
  if (!current) return steps.length === 0 ? "Getting started" : "Deciding what to do next";
  if (current.tool === "task") return "Researching";
  const { label, detail } = humanizeTool(current.tool);
  return [label, detail(current.args)].filter(Boolean).join(" ");
}

const SEGMENTS = 20;

function status(r: BoardRow): string {
  if (r.state === "paused") return "Paused";
  if (r.state === "stopped") return "Stopped";
  if (r.state === "ready") return "✓ Ready";
  if (r.state === "notFound") return "Not found";
  if (r.state === "wrong") return "Different one";
  if (r.found === null) return "Starting";
  return r.total ? `${r.found} of ${r.total} found` : `${r.found} found`;
}

/** Progress as 20 blocks, at least one lit once started. */
function Segments({ pct, className }: { pct: number; className: string }) {
  const on = Math.max(1, Math.round(pct / (100 / SEGMENTS)));
  return (
    <span className={className} aria-hidden>
      {Array.from({ length: SEGMENTS }, (_, i) => (
        <span key={i} className="import-block" data-on={i < on} />
      ))}
    </span>
  );
}

function Row({ row }: { row: BoardRow }) {
  const [open, setOpen] = useState(false);
  const pages = row.pages.length;
  const finished = row.state === "ready";
  return (
    <li className="import-board-item" data-state={row.state}>
      <button
        type="button"
        className="import-board-row"
        onClick={() => setOpen(!open)}
        aria-expanded={pages > 0 ? open : undefined}
        disabled={pages === 0}
      >
        <span className="import-board-name">
          <EntityMark name={row.name} size={26} />
          <strong>{row.name}</strong>
        </span>
        {finished ? (
          <span className="import-bar-done" aria-hidden />
        ) : (
          <Segments pct={row.pct} className="import-segs import-segs-mini" />
        )}
        <span className="import-board-now">{row.now}</span>
        <span className="import-board-status">{status(row)}</span>
      </button>
      {open && pages > 0 && (
        <div className="import-board-pages">
          <span className="card-kicker">What Sangam read ({pages})</span>
          <ul>
            {row.pages.map((p) => (
              <li key={p.id} className="import-page">
                <span className="import-page-name">
                  <strong>{p.title}</strong> {p.where}
                </span>
                <span className="import-page-state" data-state={p.state}>
                  {p.text}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The run's headline and the line under it. */
function runTitle(steps: TraceStep[], running: boolean, paused: boolean, laneOwners: Record<string, string>) {
  const rows = boardOf(steps, running, laneOwners, paused).rows;
  const finished = rows.length > 0 && rows.every((r) => r.state === "ready");
  // Every organisation is researched and the run goes on: the only thing left is saving what was approved.
  const saving = finished && running;
  const title = saving
    ? "Saving to Sangam…"
    : finished
      ? "Research finished"
      : rows.length > 0
        ? `Scout is researching ${plural(rows.length, "organisation")}`
        : running
          ? "Scout is working"
          : paused
            ? "Paused — waiting for you"
            : "Finished";
  const sub = saving
    ? "Writing what you approved into the profiles."
    : finished
      ? "Nothing is saved yet. Look through what was found, then choose what to keep."
      : "This usually takes a few minutes for each one. You can leave this page open and come back.";
  return { title, sub, count: rows.length };
}

/** A run's progress: a title, one line of totals, a row per organisation, and the last few things that happened. */
export function WorkingBoard({
  steps,
  running,
  paused,
  laneOwners,
  compact = false,
}: {
  steps: TraceStep[];
  running: boolean;
  paused: boolean;
  laneOwners: Record<string, string>;
  /** Inside the pinned panel, whose header already carries the title. */
  compact?: boolean;
}) {
  const board = boardOf(steps, running, laneOwners, paused);
  if (steps.length === 0 && !running) return null;
  const rows = board.rows;
  const { title, sub } = runTitle(steps, running, paused, laneOwners);
  // Without rows (a news import), or rows no step could be tied to, this line is the only sign of what is happening.
  const showLine = rows.length === 0 || (running && !board.attributed);
  const from = readingFrom(steps);
  const line = !running
    ? paused
      ? "Paused — waiting for you"
      : "Finished"
    : rows.length > 0
      ? (board.now ?? doing(steps))
      : doing(steps);

  return (
    <section className="import-working" aria-label="Progress">
      {compact ? (
        from && <p className="import-reading-from">Reading from: {from}</p>
      ) : (
        <div className="import-head">
          <h1 className="import-h1">{title}</h1>
          <p className="import-sub">{sub}</p>
          {from && <p className="import-reading-from">Reading from: {from}</p>}
        </div>
      )}
      <div className="import-board">
        <div className="import-board-head">
          <div className="import-board-stats">
            {rows.length > 0 && (
              <span className="import-stat">
                <strong>
                  {board.ready} of {rows.length}
                </strong>{" "}
                ready
              </span>
            )}
            <span className="import-stat">
              <strong>{board.pagesRead}</strong> pages read
            </span>
            {rows.length > 0 && (
              <span className="import-stat">
                <strong>{board.answers}</strong> answers found
              </span>
            )}
          </div>
          {rows.length > 0 && (
            <div role="progressbar" aria-label="Overall progress" aria-valuenow={board.pct} aria-valuemin={0} aria-valuemax={100}>
              <Segments pct={board.pct} className="import-segs" />
            </div>
          )}
          {showLine && (
            <p className="import-board-line" role="status" aria-live="polite">
              <span className={running ? "import-live sangam-pulse" : "import-live"} data-running={running} aria-hidden />
              {line}
            </p>
          )}
        </div>
        {rows.length > 0 && (
          <ul className="import-board-rows">
            {rows.map((r) => (
              <Row key={r.id} row={r} />
            ))}
          </ul>
        )}
      </div>

      {board.events.length > 0 && (
        <div className="import-feed">
          <span className="card-kicker">Just now</span>
          <ol aria-live="polite">
            {board.events.map((e) => (
              <li key={e.id}>
                {e.name && <EntityMark name={e.name} size={20} />}
                <span className="import-feed-text">
                  {e.name && <strong>{e.name}</strong>} {e.text}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
