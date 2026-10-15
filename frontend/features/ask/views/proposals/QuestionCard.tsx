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

type Suggested = { type: "proposal_suggestion"; ask: string; part: string; now: string; better: string; why: string };

// ask_user's and suggest_edit's interrupts (QUESTION, SUGGESTION in app/proposals/tools/); any other is not ours.
function asked(value: unknown): Asked | Suggested | null {
  let v = value;
  if (typeof v === "string") {
    try {
      v = JSON.parse(v);
    } catch {
      return null;
    }
  }
  const type = (v as Asked | Suggested | null)?.type;
  return type === "proposal_question" || type === "proposal_suggestion" ? (v as Asked | Suggested) : null;
}

/** Sangam Pitch's one open question or suggestion, as the chat's latest message while the run waits for the reply. */
export function QuestionCard({ agentId, onOpen }: { agentId: string; onOpen: (answer: ((r: Reply) => void) | null) => void }) {
  return useInterrupt({
    agentId,
    renderInChat: false,
    enabled: (event) => asked(event.value) !== null,
    render: ({ event, resolve }) => {
      const q = asked(event.value);
      if (!q) return <></>;
      return q.type === "proposal_suggestion" ? (
        <Suggestion key={q.ask} s={q} resolve={resolve} onOpen={onOpen} />
      ) : (
        <Card key={q.ask} q={q} resolve={resolve} onOpen={onOpen} />
      );
    },
  });
}

type Answer = { resolve: (r: Reply) => unknown; onOpen: (answer: ((r: Reply) => void) | null) => void };

/** One reply per card, from its buttons or from the chat box under it. */
function useReply({ resolve, onOpen }: Answer) {
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
  return { sent, reply };
}

function Card({ q, ...answer }: { q: Asked } & Answer) {
  const { sent, reply } = useReply(answer);
  return (
    <section className="card pr-side-card pr-question" aria-label="Sangam Pitch asks">
      <div className="eyebrow">Sangam Pitch needs one answer · {q.part}</div>
      <p className="pr-question-ask">{q.missing}</p>
      <p>
        <strong>What Sangam found:</strong> {q.found}
      </p>
      {q.why && (
        <p>
          <strong>Why it matters:</strong> {q.why}
        </p>
      )}
      {q.suggestion && (
        <p>
          <strong>Where to find it:</strong> {q.suggestion}
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
      <p className="muted pr-chat-note">{sent ? "Sent." : "Type your answer in the box below and press Reply. Not sure yet? Press Later."}</p>
    </section>
  );
}

function Suggestion({ s, ...answer }: { s: Suggested } & Answer) {
  const { sent, reply } = useReply(answer);
  return (
    <section className="card pr-side-card pr-question" aria-label="Sangam Pitch suggests">
      <div className="eyebrow">Sangam Pitch suggests · {s.part}</div>
      <p className="pr-suggest-now">{s.now}</p>
      <p className="pr-suggest-better">{s.better}</p>
      {s.why && <p className="muted">{s.why}</p>}
      <div className="pr-question-actions">
        <button className="btn btn-primary" type="button" disabled={sent} onClick={() => reply({ kind: "pick", choice: "use" })}>
          Use this
        </button>
        <button className="btn btn-ghost" type="button" disabled={sent} onClick={() => reply({ kind: "pick", choice: "keep" })}>
          Keep mine
        </button>
      </div>
      <p className="muted pr-chat-note">{sent ? "Sent." : "Or say what you would change, in the box below."}</p>
    </section>
  );
}
