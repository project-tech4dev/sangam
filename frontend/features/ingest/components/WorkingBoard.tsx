"use client";

import { useState } from "react";
import { EntityMark } from "@/components/ui/primitives";
import type { TraceStep } from "@/lib/useAgentChat";
import { boardOf, type BoardRow } from "../lib/board";
import { humanizeTool } from "../lib/toolLabels";

/** The step in flight, for runs with no organisations to show (a news import) or none tied yet. */
function doing(steps: TraceStep[]): string {
  const current = steps.filter((s) => s.running).at(-1);
  if (!current) return steps.length === 0 ? "Getting started" : "Deciding what to do next";
  if (current.tool === "task") return "Researching";
  const { label, detail } = humanizeTool(current.tool);
  return [label, detail(current.args)].filter(Boolean).join(" ");
}

function status(r: BoardRow): string {
  if (r.state === "stopped") return "Stopped";
  if (r.state === "ready") return "✓ Ready";
  if (r.state === "notFound") return "Not found";
  if (r.state === "wrong") return "Different one";
  if (r.found === null) return "Starting";
  return r.total ? `${r.found} of ${r.total} found` : `${r.found} found`;
}

function Row({ row }: { row: BoardRow }) {
  const [open, setOpen] = useState(false);
  const pages = row.pages.length;
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
        <span className="import-bar import-bar-mini" aria-hidden>
          <span className="import-bar-fill" style={{ width: `${row.pct}%` }} />
        </span>
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

/** The Working step: one line of totals, a row per organisation, and the last few things that happened. */
export function WorkingBoard({
  steps,
  running,
  laneOwners,
}: {
  steps: TraceStep[];
  running: boolean;
  laneOwners: Record<string, string>;
}) {
  const board = boardOf(steps, running, laneOwners);
  if (steps.length === 0 && !running) return null;
  const rows = board.rows;
  const line = !running ? "Finished" : rows.length > 0 && !board.attributed ? (board.now ?? doing(steps)) : doing(steps);

  return (
    <section className="import-working" aria-label="Progress">
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
            <div className="import-bar" role="progressbar" aria-label="Overall progress" aria-valuenow={board.pct} aria-valuemin={0} aria-valuemax={100}>
              <span className="import-bar-fill" style={{ width: `${board.pct}%` }} />
            </div>
          )}
          <p className="import-board-line" role="status" aria-live="polite">
            <span className={running ? "import-live sangam-pulse" : "import-live"} data-running={running} aria-hidden />
            {line}
          </p>
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
          <ol>
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
