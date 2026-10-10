"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Maximize2, Minimize2 } from "lucide-react";
import { StepBar } from "./StepBar";

/** One strip over the thread: where the run is, and a button that drops its detail down over the chat. */
export function ScoutRunPanel({
  step,
  status,
  action,
  live,
  open,
  onToggle,
  tall,
  children,
}: {
  step: number;
  status: string;
  /** The button's label while closed; null when there is no detail to show. */
  action: string | null;
  live: boolean;
  open: boolean;
  onToggle: () => void;
  /** Review and Done need the room; the Working board should leave the thread in view. */
  tall: boolean;
  children: ReactNode;
}) {
  // The detail blown up to most of the screen, for reading every row at once.
  const [full, setFull] = useState(false);

  useEffect(() => {
    if (!full) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setFull(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [full]);

  const head = (
    <div className="scout-run-head">
      <StepBar current={step} size="sm" />
      <span className="scout-run-status">
        <span className={live ? "import-live sangam-pulse" : "import-live"} data-running={live} aria-hidden />
        {status}
      </span>
      {action && !full && (
        <button type="button" className="btn btn-secondary scout-run-toggle" aria-expanded={open} onClick={onToggle}>
          {open ? "Close ✕" : action}
        </button>
      )}
      {action && (
        <button
          type="button"
          className="btn btn-ghost btn-icon"
          aria-label={full ? "Back to the chat" : "Open full size"}
          title={full ? "Back to the chat (Esc)" : "Open full size"}
          onClick={() => setFull(!full)}
        >
          {full ? <Minimize2 className="icon icon-sm" aria-hidden /> : <Maximize2 className="icon icon-sm" aria-hidden />}
        </button>
      )}
    </div>
  );

  return (
    <section className="card elev-sm scout-run" aria-label="This run">
      {head}
      {full ? (
        <div className="dialog-backdrop" onClick={(e) => e.target === e.currentTarget && setFull(false)}>
          <div className="scout-run-full" role="dialog" aria-modal="true" aria-label="This run, full size">
            {head}
            <div className="scout-run-full-body">{children}</div>
          </div>
        </div>
      ) : (
        // Kept mounted while hidden: the Done cards report how many still wait for review, which sets the step.
        action && (
          <div className="card elev-md scout-run-body" data-tall={tall} hidden={!open}>
            {children}
          </div>
        )
      )}
    </section>
  );
}
