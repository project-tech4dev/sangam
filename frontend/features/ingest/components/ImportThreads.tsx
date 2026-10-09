"use client";

import { PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import type { ThreadMeta } from "@/features/ask/lib/threads";

const MONTH = new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric" });
const DAY = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });

/** Past imports, newest first and grouped by month, each opening its thread. */
export function ImportThreads({
  threads,
  active,
  error,
  collapsed,
  onToggle,
  onPick,
  onNew,
}: {
  threads: ThreadMeta[] | null;
  active: string;
  error: boolean;
  collapsed: boolean;
  onToggle: () => void;
  onPick: (id: string) => void;
  onNew: () => void;
}) {
  if (collapsed) {
    return (
      <div className="ask-sidebar-collapsed">
        <button type="button" className="rail-mini" onClick={onToggle} title="Past imports" aria-label="Show past imports">
          <PanelLeftOpen className="icon" aria-hidden />
        </button>
        <button type="button" className="rail-mini rail-mini-new" onClick={onNew} title="New import" aria-label="New import">
          <Plus className="icon" aria-hidden />
        </button>
      </div>
    );
  }

  const rows: React.ReactNode[] = [];
  let month = "";
  for (const t of threads ?? []) {
    const when = new Date(t.createdAt);
    const label = MONTH.format(when);
    if (label !== month) {
      month = label;
      rows.push(
        <span key={`m-${label}`} className="eyebrow import-threads-month">
          {label}
        </span>,
      );
    }
    rows.push(
      <button
        key={t.id}
        type="button"
        className="rail-item import-threads-row"
        data-active={t.id === active}
        aria-current={t.id === active ? "page" : undefined}
        onClick={() => onPick(t.id)}
        title={t.title}
      >
        <span className="import-threads-title">{t.title}</span>
        <span className="import-threads-date">{DAY.format(when)}</span>
      </button>,
    );
  }

  return (
    <nav className="ask-sidebar" aria-label="Past imports">
      <div className="rail-head">
        <span className="eyebrow">Imports</span>
        <button type="button" className="rail-mini rail-collapse" onClick={onToggle} title="Collapse" aria-label="Hide past imports">
          <PanelLeftClose className="icon" aria-hidden />
        </button>
      </div>
      <button type="button" className="btn btn-tint" onClick={onNew}>
        + New import
      </button>
      <div className="rail-scroll import-threads">
        {threads === null && !error && <span className="muted-2 rail-empty">Loading…</span>}
        {error && <span className="muted-2 rail-empty">Couldn&apos;t load past imports.</span>}
        {threads?.length === 0 && <span className="muted-2 rail-empty">No past imports yet.</span>}
        {rows}
      </div>
    </nav>
  );
}
