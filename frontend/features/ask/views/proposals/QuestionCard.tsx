"use client";

import { useEffect, useRef, useState } from "react";
import { useInterrupt } from "@copilotkit/react-core/v2";

/** A card button sends a pick; the chat box under it sends text, which Sangam Pitch sorts. */
export type Reply = { kind: "pick"; choice: string } | { kind: "text"; text: string };

type Asked = {
  type: "proposal_question";
  id: string;
  ask: string;
  part: string;
  subject: string;
  found: string;
  missing: string;
  why: string;
  suggestion: string;
  options: string[];
};

// ask_user's interrupt (app/proposals/tools/ledger_tools.py QUESTION); any other interrupt is not ours.
function asked(value: unknown): Asked | null {
  let v = value;
  if (typeof v === "string") {
    try {
      v = JSON.parse(v);
    } catch {
      return null;
    }
  }
  return (v as Asked | null)?.type === "proposal_question" ? (v as Asked) : null;
}

/** Sangam Pitch's one open question, at the top of the side panel while the run waits for the reply. */
export function QuestionCard({ agentId, onOpen }: { agentId: string; onOpen: (answer: ((r: Reply) => void) | null) => void }) {
  return useInterrupt({
    agentId,
    renderInChat: false,
    enabled: (event) => asked(event.value) !== null,
    render: ({ event, resolve }) => {
      const q = asked(event.value);
      return q ? <Card key={q.ask} q={q} resolve={resolve} onOpen={onOpen} /> : <></>;
    },
  });
}

function Card({ q, resolve, onOpen }: { q: Asked; resolve: (r: Reply) => unknown; onOpen: (answer: ((r: Reply) => void) | null) => void }) {
  const [sent, setSent] = useState(false);
  const latest = useRef(resolve);
  useEffect(() => {
    latest.current = resolve;
  });

  const reply = (r: Reply) => {
    setSent(true);
    void latest.current(r);
  };
  // The chat box answers this card while it is open.
  useEffect(() => {
    onOpen((r) => {
      setSent(true);
      void latest.current(r);
    });
    return () => onOpen(null);
  }, [onOpen]);

  return (
    <section className="card pr-side-card pr-question" aria-label="Sangam Pitch asks">
      <div className="card-title">Sangam Pitch asks</div>
      <div className="eyebrow">{q.part}</div>
      <p>
        <strong>Found:</strong> {q.found}
      </p>
      <p>
        <strong>Missing:</strong> {q.missing}
      </p>
      <p className="muted">{q.why}</p>
      {q.suggestion && (
        <p>
          <strong>Suggestion:</strong> {q.suggestion}
        </p>
      )}
      <div className="pr-question-actions">
        {q.options.map((o) => (
          <button key={o} className="btn" type="button" disabled={sent} onClick={() => reply({ kind: "pick", choice: o })}>
            {o}
          </button>
        ))}
        <button className="btn btn-ghost" type="button" disabled={sent} onClick={() => reply({ kind: "pick", choice: "later" })}>
          Later
        </button>
      </div>
      <p className="muted pr-chat-note">{sent ? "Sent." : "Or type your answer, or a question about it, in the box below."}</p>
    </section>
  );
}
