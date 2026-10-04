"use client";

import { useState } from "react";
import type { ThreadMeta } from "../lib/threads";

export type WorkspaceView = "ask" | "vault" | "media" | "rfpwatch" | "import";

const CONTEXT_ITEMS: { id: WorkspaceView; label: string }[] = [
  { id: "vault", label: "Doc vault" },
  { id: "media", label: "Media & signals" },
  { id: "rfpwatch", label: "RFP watch" },
];

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
  const [toolsOpen, setToolsOpen] = useState(view === "import");

  if (collapsed) {
    return (
      <div style={{ width: 40, flexShrink: 0, borderRight: "1px solid var(--color-divider)", display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 14, gap: 10 }}>
        <button className="btn btn-ghost" style={{ padding: 2 }} onClick={onToggle} title="Open workspace">
          ⟩
        </button>
      </div>
    );
  }

  const itemStyle = (active: boolean) =>
    ({
      display: "block",
      width: "100%",
      textAlign: "left",
      border: "none",
      background: active ? "var(--color-accent-2-100)" : "transparent",
      color: active ? "var(--color-accent-2-900)" : "var(--color-text)",
      fontFamily: "var(--font-body)",
      fontSize: "var(--fs-sm)",
      fontWeight: 600,
      padding: "8px 12px",
      borderRadius: "var(--radius-row)",
      cursor: "pointer",
    }) as const;

  return (
    <div
      className="ask-sidebar"
      style={{
        width: 250,
        flexShrink: 0,
        borderRight: "1px solid var(--color-divider)",
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 14,
        background: "var(--color-surface)",
        minHeight: 0,
      }}
    >
      {/* The global navbar carries the wordmark, site links and the signed-in user. */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="eyebrow">Workspace</span>
        <button className="btn btn-ghost" style={{ padding: 2, marginLeft: "auto" }} onClick={onToggle} title="Collapse">
          ⟨
        </button>
      </div>

      <button
        className="btn"
        style={{ background: "var(--color-accent-2-100)", color: "var(--color-accent-2-900)", justifyContent: "flex-start" }}
        onClick={onNewChat}
      >
        + New chat
      </button>

      {/* Only the lists scroll, so Tools stays in view however many conversations there are. */}
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span className="eyebrow" style={{ padding: "0 12px" }}>Recent</span>
        {threads.length === 0 ? (
          <span className="muted-2" style={{ fontSize: "var(--fs-xs)", padding: "4px 12px" }}>No past conversations yet.</span>
        ) : (
          threads.slice(0, 6).map((thread) => (
            <button
              key={thread.id}
              style={{ ...itemStyle(view === "ask" && thread.id === activeThread), fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
              onClick={() => onPickThread(thread.id)}
              title={thread.title}
            >
              {thread.title}
            </button>
          ))
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span className="eyebrow" style={{ padding: "0 12px" }}>Context</span>
        {CONTEXT_ITEMS.map((item) => (
          <button key={item.id} style={itemStyle(view === item.id)} onClick={() => onView(item.id)}>
            {item.label}
          </button>
        ))}
      </div>
      </div>

      {/* Tools that change the data, kept apart from conversations at the foot of the rail.
          Everyone resolves to the staff dev user until real auth lands, so this is not yet
          gated; Phase 3 shows it only when /api/me says is_staff. */}
      <div style={{ flexShrink: 0, display: "flex", flexDirection: "column", gap: 4, borderTop: "1px solid var(--color-divider)", paddingTop: 12 }}>
        <button
          type="button"
          aria-expanded={toolsOpen}
          onClick={() => setToolsOpen(!toolsOpen)}
          className="eyebrow"
          style={{ display: "flex", alignItems: "center", gap: 6, padding: "0 12px", border: "none", background: "none", cursor: "pointer", textAlign: "left" }}
        >
          Tools
          {/* The design system's chevron glyph, turned to point down when open. */}
          <span aria-hidden style={{ display: "inline-block", transform: toolsOpen ? "rotate(90deg)" : "none", transition: "transform 0.12s ease" }}>
            ⟩
          </span>
        </button>
        {toolsOpen && (
          <button style={itemStyle(view === "import")} onClick={() => onView("import")}>
            Import
          </button>
        )}
      </div>
    </div>
  );
}
