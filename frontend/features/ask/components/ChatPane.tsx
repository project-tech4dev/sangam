"use client";

import { useEffect, useRef, useState } from "react";
import { Mic, Paperclip } from "lucide-react";
import type { RegistryIndex } from "../lib/citations";
import { saveThread, titleFrom } from "../lib/threads";
import { useSangamChat } from "../lib/useSangamChat";
import { AnswerCard } from "./AnswerCard";
import { ComposerNotice } from "./ComposerNotice";
import { TraceCard } from "./TraceCard";

const SUGGESTIONS = [
  "How well does KABIL fit Axis Bank Foundation, and why?",
  "Which organisations in the base work in Assam?",
  "What grants has KABIL received?",
  "What connects KABIL to Tata Trusts?",
];

export function ChatPane({
  threadId,
  resume,
  seed,
  onFirstSend,
  index,
  onLatestTurn,
}: {
  threadId: string;
  resume: boolean;
  seed: string | null;
  onFirstSend: () => void;
  index: RegistryIndex | null;
  onLatestTurn: (turn: ReturnType<typeof useSangamChat>["turns"][number] | null) => void;
}) {
  const { turns, send, isRunning, isReady: agentReady, isLoadingHistory } = useSangamChat(threadId, resume);
  // Not ready while a past chat loads, so a question typed meanwhile is not replaced by its history.
  const isReady = agentReady && !isLoadingHistory;
  const [draft, setDraft] = useState(seed ?? "");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sentTitle = useRef(resume);

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
    // A suggestion pill disappears once sent; keep the cursor in the box for the follow-up.
    inputRef.current?.focus();
    if (!sentTitle.current) {
      saveThread({ id: threadId, title: titleFrom(question), createdAt: Date.now() });
      sentTitle.current = true;
      onFirstSend();
    }
    await send(question);
  }

  const composer = (
    <div className="card elev-sm composer">
      <textarea
        ref={inputRef}
        className="input composer-input"
        placeholder="Ask about an organisation, a funder, or a fit…"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") submit();
        }}
      />
      <div className="composer-row">
        <span className="muted-2 composer-hint">{isReady ? "⌘↵ to send" : isLoadingHistory && agentReady ? "Loading this chat…" : "Connecting to the agent…"}</span>
        <div className="composer-actions">
          {/* Stubs: attaching a file and asking by voice are not built yet. */}
          <button type="button" className="btn btn-icon composer-stub" aria-disabled="true" title="Attach a file (coming soon)" aria-label="Attach a file (coming soon)">
            <Paperclip className="icon icon-sm" aria-hidden />
          </button>
          <button type="button" className="btn btn-icon composer-stub" aria-disabled="true" title="Ask by voice (coming soon)" aria-label="Ask by voice (coming soon)">
            <Mic className="icon icon-sm" aria-hidden />
          </button>
          <button className="btn btn-primary" onClick={() => submit()} disabled={!isReady || isRunning || !draft.trim()}>
            {isRunning ? "Working…" : "Ask Sangam"}
          </button>
        </div>
      </div>
      <ComposerNotice />
    </div>
  );

  // A past chat that is still loading is not a new one: no greeting or suggestions while it arrives.
  const empty = turns.length === 0 && !isLoadingHistory;

  // One tree for both states, with the question box always the second child, so React keeps
  // the same textarea when the first question is sent and the cursor stays in it.
  return (
    <div className={empty ? "chat-pane is-empty" : "chat-pane"}>
      {empty ? (
        <h2 className="chat-empty-title">What do you want to know?</h2>
      ) : (
        <div className="chat-scroll">
          <div className="chat-turns">
            {turns.map((turn) => (
              <div key={turn.id} className="chat-turn">
                <div className="chat-question">
                  <div aria-hidden className="chat-you">
                    You
                  </div>
                  <div className="chat-question-text">{turn.question}</div>
                </div>
                <TraceCard steps={turn.steps} streaming={turn.streaming && !turn.answer} />
                {turn.answer && <AnswerCard answer={turn.answer} index={index} />}
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        </div>
      )}
      {composer}
      {empty && (
        <div className="chat-suggestions">
          {SUGGESTIONS.map((s) => (
            <button key={s} className="pill" onClick={() => submit(s)} disabled={!isReady}>
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
