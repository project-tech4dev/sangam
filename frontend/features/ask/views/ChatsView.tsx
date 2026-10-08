"use client";

import { useState } from "react";
import type { ThreadMeta } from "../lib/threads";

const MONTH = new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric" });
const DAY = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });

/* Every saved chat, newest first and grouped by month. The sidebar shows only the last five.
   Search matches titles: the conversations themselves live in the checkpointer, not here. */
export function ChatsView({ threads, onPick }: { threads: ThreadMeta[]; onPick: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const shown = threads.filter((t) => t.title.toLowerCase().includes(query.trim().toLowerCase()));

  const rows: React.ReactNode[] = [];
  let month = "";
  for (const thread of shown) {
    const when = new Date(thread.createdAt);
    const label = MONTH.format(when);
    if (label !== month) {
      month = label;
      rows.push(
        <div key={`m-${label}`} className="eyebrow chat-list-month">
          {label}
        </div>,
      );
    }
    rows.push(
      <button key={thread.id} type="button" className="chat-list-row" onClick={() => onPick(thread.id)} title={thread.title}>
        <span className="chat-list-title">{thread.title}</span>
        <span className="muted chat-list-date">{DAY.format(when)}</span>
      </button>,
    );
  }

  return (
    <div className="view view-measure">
      <div>
        <div className="eyebrow">Recent Chats</div>
        <h2 className="view-title">All Chats</h2>
      </div>
      <input
        className="input"
        type="search"
        placeholder="Search your chats"
        aria-label="Search your chats"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {threads.length === 0 ? (
        <div className="card">
          <div className="card-body">No past conversations yet.</div>
        </div>
      ) : (
        <div className="card chat-list">
          {rows.length > 0 ? rows : <div className="muted chat-list-empty">No chats match.</div>}
        </div>
      )}
    </div>
  );
}
