"use client";

import { useState } from "react";
import type { ThreadMeta } from "../lib/threads";

export type WorkspaceView = "ask" | "vault" | "media" | "rfpwatch" | "import";

const CONTEXT_ITEMS: { id: WorkspaceView; label: string }[] = [
  { id: "vault", label: "Doc vault" },
  { id: "media", label: "Media & signals" },
  { id: "rfpwatch", label: "RFP watch" },
];

/* A section header that opens and closes the section below it. The chevron is the
   design system's glyph, turned to point down when open (.rail-toggle in globals.css). */
function SectionToggle({ label, open, onToggle }: { label: string; open: boolean; onToggle: () => void }) {
  return (
    <button type="button" className="eyebrow rail-toggle" aria-expanded={open} onClick={onToggle}>
      {label}
      <span aria-hidden className="rail-chevron">⟩</span>
    </button>
  );
}

export function Sidebar({
  collapsed,
  onToggle,
  view,
  onView,
  threads,
  activeThread,
  onPickThread,
  onNewChat,
}: {
  collapsed: boolean;
  onToggle: () => void;
  view: WorkspaceView;
  onView: (v: WorkspaceView) => void;
  threads: ThreadMeta[];
  activeThread: string;
  onPickThread: (id: string) => void;
  onNewChat: () => void;
}) {
  const [recentOpen, setRecentOpen] = useState(true);
  const [toolsOpen, setToolsOpen] = useState(view === "import");

  if (collapsed) {
    return (
      <div className="ask-sidebar-collapsed">
        <button className="btn btn-ghost rail-icon" onClick={onToggle} title="Open workspace">
          ⟩
        </button>
      </div>
    );
  }

  return (
    <div className="ask-sidebar">
      {/* The global navbar carries the wordmark, site links and the signed-in user. */}
      <div className="rail-head">
        <span className="eyebrow">Workspace</span>
        <button className="btn btn-ghost rail-icon" onClick={onToggle} title="Collapse">
          ⟨
        </button>
      </div>

      <button className="btn btn-tint" onClick={onNewChat}>
        + New chat
      </button>

      <div className="rail-scroll">
        <div className="rail-section">
          <SectionToggle label="Recent chats" open={recentOpen} onToggle={() => setRecentOpen(!recentOpen)} />
          {recentOpen &&
            (threads.length === 0 ? (
              <span className="muted-2 rail-empty">No past conversations yet.</span>
            ) : (
              threads.slice(0, 6).map((thread) => (
                <button
                  key={thread.id}
                  className="rail-item rail-thread"
                  data-active={view === "ask" && thread.id === activeThread}
                  onClick={() => onPickThread(thread.id)}
                  title={thread.title}
                >
                  {thread.title}
                </button>
              ))
            ))}
        </div>

        <div className="rail-section">
          <span className="eyebrow rail-label">Context</span>
          {CONTEXT_ITEMS.map((item) => (
            <button key={item.id} className="rail-item" data-active={view === item.id} onClick={() => onView(item.id)}>
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tools that change the data, kept apart from conversations at the foot of the rail.
          Shown to everyone: the backend answers non-staff with 403 and ImportView says "Staff only". */}
      <div className="rail-section rail-foot">
        <SectionToggle label="Tools" open={toolsOpen} onToggle={() => setToolsOpen(!toolsOpen)} />
        {toolsOpen && (
          <button className="rail-item" data-active={view === "import"} onClick={() => onView("import")}>
            Import
          </button>
        )}
      </div>
    </div>
  );
}
