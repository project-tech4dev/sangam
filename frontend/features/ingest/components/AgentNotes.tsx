"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** The agent's written report, formatted, in a box; closed when the Done cards already say the same. */
export function AgentNotes({ text, collapsed }: { text: string; collapsed: boolean }) {
  const [open, setOpen] = useState(!collapsed);
  return (
    <section className="import-notes" aria-label="Sangam's notes">
      <button type="button" className="import-notes-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="card-kicker">Sangam&apos;s full notes</span>
        <span className="import-notes-chev">{open ? "Hide ▴" : "Show ▾"}</span>
      </button>
      {open && (
        <div className="import-notes-body answer-md">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noreferrer">
                  {children}
                </a>
              ),
              table: (props) => (
                <div className="import-notes-scroll">
                  <table {...props} />
                </div>
              ),
            }}
          >
            {text}
          </ReactMarkdown>
        </div>
      )}
    </section>
  );
}
