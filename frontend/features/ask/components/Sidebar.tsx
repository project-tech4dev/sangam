"use client";

import Link from "next/link";
import type { ThreadMeta } from "../lib/threads";

export type WorkspaceView = "ask" | "vault" | "media" | "rfpwatch";

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
  if (collapsed) {
    return (
      <div style={{ width: 40, flexShrink: 0, borderRight: "1px solid var(--color-divider)", display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 14, gap: 10 }}>
        <button className="btn btn-ghost" style={{ padding: 2 }} onClick={onToggle} title="Open workspace">
          ⟩
        </button>
        <Link
          href="/registry"
          title="Back to Sangam"
          style={{ writingMode: "vertical-rl", fontFamily: "var(--font-heading)", fontWeight: 700, fontSize: 14, color: "var(--color-accent-2-900)", textDecoration: "none" }}
        >
          sangam
        </Link>
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
      fontSize: 13,
      fontWeight: 700,
      padding: "8px 12px",
      borderRadius: "var(--radius-sm)",
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
        overflowY: "auto",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Link
          href="/registry"
          style={{ fontFamily: "var(--font-heading)", fontWeight: 700, fontSize: 18, color: "var(--color-accent-2-900)", textDecoration: "none" }}
        >
          sangam
        </Link>
        <button className="btn btn-ghost" style={{ padding: 2, marginLeft: "auto" }} onClick={onToggle} title="Collapse">
          ⟨
        </button>
      </div>
      <div style={{ display: "flex", gap: 10, fontSize: 12 }}>
        <Link href="/registry">Registry</Link>
        <Link href="/resources">Resources</Link>
      </div>

      <button
        className="btn"
        style={{ background: "var(--color-accent-2-100)", color: "var(--color-accent-2-900)", justifyContent: "flex-start" }}
        onClick={onNewChat}
      >
        + New chat
      </button>

      <button style={itemStyle(view === "ask")} onClick={() => onView("ask")}>
        Ask Sangam
      </button>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span className="eyebrow" style={{ padding: "0 12px" }}>Recent</span>
        {threads.length === 0 ? (
          <span className="muted-2" style={{ fontSize: 12, padding: "4px 12px" }}>No past conversations yet.</span>
        ) : (
          threads.slice(0, 6).map((thread) => (
            <button
              key={thread.id}
              style={{ ...itemStyle(view === "ask" && thread.id === activeThread), fontWeight: 400, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
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

      <div style={{ marginTop: "auto", display: "flex", alignItems: "center", gap: 10, borderTop: "1px solid var(--color-divider)", paddingTop: 12 }}>
        <div
          aria-hidden
          style={{ width: 30, height: 30, borderRadius: "50%", background: "var(--color-neutral-700)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700 }}
        >
          DV
        </div>
        <div style={{ fontSize: 11.5 }} className="muted">
          Signed in — dev workspace
        </div>
      </div>
    </div>
  );
}
