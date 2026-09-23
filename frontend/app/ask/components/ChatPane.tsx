"use client";

import { useEffect, useRef, useState } from "react";
import type { RegistryIndex } from "../lib/citations";
import { saveThread, titleFrom } from "../lib/threads";
import { useSangamChat } from "../lib/useSangamChat";
import { AnswerCard } from "./AnswerCard";
import { TraceCard } from "./TraceCard";

const SUGGESTIONS = [
  "How well does KABIL fit Axis Bank Foundation, and why?",
  "Which organisations in the base work in Assam?",
  "What grants has KABIL received?",
  "What connects KABIL to Tata Trusts?",
];

export function ChatPane({
  threadId,
  seed,
  onFirstSend,
  index,
  onLatestTurn,
}: {
  threadId: string;
  seed: string | null;
  onFirstSend: () => void;
  index: RegistryIndex | null;
  onLatestTurn: (turn: ReturnType<typeof useSangamChat>["turns"][number] | null) => void;
}) {
  const { turns, send, isRunning, isReady } = useSangamChat(threadId);
  const [draft, setDraft] = useState(seed ?? "");
  const bottomRef = useRef<HTMLDivElement>(null);
  const sentTitle = useRef(false);

  useEffect(() => {
    onLatestTurn(turns.length > 0 ? turns[turns.length - 1]! : null);
  }, [turns, onLatestTurn]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, isRunning]);

  async function submit(text?: string) {
    const question = (text ?? draft).trim();
    if (!question || isRunning) return;
    setDraft("");
    if (!sentTitle.current) {
      saveThread({ id: threadId, title: titleFrom(question), createdAt: Date.now() });
      sentTitle.current = true;
      onFirstSend();
    }
    await send(question);
  }

  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 18 }}>
      {turns.length === 0 && (
        <>
          <div className="card" style={{ gap: 8 }}>
            <div className="card-title">Nothing asked yet</div>
            <div className="card-body">
              Ask about the cohort&apos;s organisations, funders, fit scores, or the connections
              between them. Answers cite the Registry — and say so when the base has no answer.
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {SUGGESTIONS.map((s) => (
              <button key={s} className="pill" onClick={() => submit(s)} disabled={!isReady}>
                {s}
              </button>
            ))}
          </div>
        </>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
        {turns.map((turn) => (
          <div key={turn.id} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
              <div
                aria-hidden
                style={{ width: 34, height: 34, borderRadius: "50%", flexShrink: 0, background: "var(--color-neutral-700)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700 }}
              >
                You
              </div>
              <div style={{ fontFamily: "var(--font-heading)", fontSize: 17, fontWeight: 600, paddingTop: 5 }}>
                {turn.question}
              </div>
            </div>
            <TraceCard steps={turn.steps} streaming={turn.streaming && !turn.answer} />
            {turn.answer && <AnswerCard answer={turn.answer} index={index} />}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="card elev-sm" style={{ gap: 10, marginTop: "auto", position: "sticky", bottom: 16 }}>
        <textarea
          className="input"
          style={{ border: "none", padding: 4, minHeight: 48 }}
          placeholder="Ask about an organisation, a funder, or a fit…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") submit();
          }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="muted-2" style={{ fontSize: 11.5 }}>
            {isReady ? "⌘↵ to send" : "Connecting to the agent…"}
          </span>
          <button
            className="btn btn-primary"
            style={{ marginLeft: "auto" }}
            onClick={() => submit()}
            disabled={!isReady || isRunning || !draft.trim()}
          >
            {isRunning ? "Working…" : "Ask Sangam"}
          </button>
        </div>
      </div>
    </div>
  );
}
