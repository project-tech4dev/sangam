"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ChevronDown,
  Folder,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Target,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import type { ThreadMeta } from "../lib/threads";

export type WorkspaceView = "ask" | "chats" | "funder-match" | "rfpwatch" | "vault" | "media";

type Item = { id: WorkspaceView; label: string; soon?: boolean };
type SectionId = "recent" | "usecases" | "context" | "tools";

const USE_CASES: Item[] = [
  { id: "funder-match", label: "Funder Match", soon: true },
  { id: "rfpwatch", label: "RFP Watch" },
  { id: "media", label: "Media & Signals" },
];

const CONTEXT_ITEMS: Item[] = [{ id: "vault", label: "Doc Vault" }];

/* The sidebar lists this many recent chats; "Show all" opens the rest in the main area. */
const RECENT_LIMIT = 5;

/* Icons are Lucide's; size, stroke and colour come from .icon in globals.css. */
const SECTION_ICONS: Record<SectionId, LucideIcon> = {
  recent: MessageSquare,
  usecases: Target,
  context: Folder,
  tools: Wrench,
};

/* A section that opens and closes. The whole header row is the target, and its chevron
   points down when open (.rail-toggle in globals.css). */
function Section({
  label,
  open,
  onToggle,
  className = "",
  children,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`rail-section ${className}`}>
      <button type="button" className="rail-toggle" aria-expanded={open} onClick={onToggle}>
        <span className="eyebrow">{label}</span>
        <ChevronDown className="icon rail-chevron" aria-hidden />
      </button>
      {open && children}
    </div>
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
  // Held here rather than in each section, so the collapsed rail can open the sidebar at one.
  const [open, setOpen] = useState<Record<SectionId, boolean>>({
    recent: true,
    usecases: true,
    context: true,
    tools: false,
  });
  const toggle = (id: SectionId) => setOpen((o) => ({ ...o, [id]: !o[id] }));

  if (collapsed) {
    const jump = (id: SectionId) => {
      setOpen((o) => ({ ...o, [id]: true }));
      onToggle();
    };
    const sections: [SectionId, string][] = [
      ["recent", "Recent Chats"],
      ["usecases", "Use Cases"],
      ["context", "Context"],
    ];
    return (
      <div className="ask-sidebar-collapsed">
        <button type="button" className="rail-mini" onClick={onToggle} title="Open Workspace" aria-label="Open Workspace">
          <PanelLeftOpen className="icon" aria-hidden />
        </button>
        <button type="button" className="rail-mini rail-mini-new" onClick={onNewChat} title="New Chat" aria-label="New Chat">
          <Plus className="icon" aria-hidden />
        </button>
        <span className="rail-mini-rule" aria-hidden />
        {sections.map(([id, label]) => {
          const SectionIcon = SECTION_ICONS[id];
          return (
            <button key={id} type="button" className="rail-mini" onClick={() => jump(id)} title={label} aria-label={label}>
              <SectionIcon className="icon" aria-hidden />
            </button>
          );
        })}
        <button type="button" className="rail-mini rail-mini-foot" onClick={() => jump("tools")} title="Tools" aria-label="Tools">
          <Wrench className="icon" aria-hidden />
        </button>
      </div>
    );
  }

  const items = (list: Item[]) =>
    list.map((item) => (
      <button key={item.id} className="rail-item" data-active={view === item.id} onClick={() => onView(item.id)}>
        {item.label}
        {item.soon && <span className="tag tag-outline rail-soon">Soon</span>}
      </button>
    ));

  return (
    <div className="ask-sidebar">
      {/* The global navbar carries the wordmark, site links and the signed-in user. */}
      <div className="rail-head">
        <span className="eyebrow">Workspace</span>
        <button type="button" className="rail-mini rail-collapse" onClick={onToggle} title="Collapse" aria-label="Collapse Workspace">
          <PanelLeftClose className="icon" aria-hidden />
        </button>
      </div>

      <button className="btn btn-tint" onClick={onNewChat}>
        + New Chat
      </button>

      {/* Only the lists scroll, so Tools stays in view however many conversations there are. */}
      <div className="rail-scroll">
        <Section label="Recent Chats" open={open.recent} onToggle={() => toggle("recent")}>
          {threads.length === 0 ? (
            <span className="muted-2 rail-empty">No past conversations yet.</span>
          ) : (
            <>
              {threads.slice(0, RECENT_LIMIT).map((thread) => (
                <button
                  key={thread.id}
                  className="rail-item rail-thread"
                  data-active={view === "ask" && thread.id === activeThread}
                  onClick={() => onPickThread(thread.id)}
                  title={thread.title}
                >
                  {thread.title}
                </button>
              ))}
              {threads.length > RECENT_LIMIT && (
                <button type="button" className="rail-more" onClick={() => onView("chats")}>
                  Show All {threads.length} Chats →
                </button>
              )}
            </>
          )}
        </Section>

        <Section label="Use Cases" open={open.usecases} onToggle={() => toggle("usecases")}>
          {items(USE_CASES)}
        </Section>

        <Section label="Context" open={open.context} onToggle={() => toggle("context")}>
          {items(CONTEXT_ITEMS)}
        </Section>
      </div>

      {/* Tools that change the data, kept apart from conversations at the foot of the rail.
          Shown to everyone: the backend answers non-staff with 403 and /import says "Staff only". */}
      <Section label="Tools" open={open.tools} onToggle={() => toggle("tools")} className="rail-foot">
        <Link href="/import" className="rail-item">
          Import
        </Link>
      </Section>
    </div>
  );
}
