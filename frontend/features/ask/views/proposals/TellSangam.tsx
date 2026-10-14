"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAgentContext } from "@copilotkit/react-core/v2";
import { useAgentChat } from "@/lib/useAgentChat";
import { AnswerCard } from "../../components/AnswerCard";
import { TraceCard } from "../../components/TraceCard";
import { fetchProposalMessages, type Proposal } from "./api";

// The backend's ProposalContext looks this description up (app/proposals/context.py SCREEN).
const SCREEN = "What the person is looking at";

export type Screen = { step: string; tab?: string; part?: string; selection?: string };

/** Your own chat with Sangam about this proposal, in the side panel; teammates each have theirs. */
export function TellSangam({ proposal, screen, onTurnEnd }: { proposal: Proposal; screen: Screen; onTurnEnd: () => void }) {
  const threadId = proposal.thread_id;
  const load = useCallback(() => fetchProposalMessages(proposal.id), [proposal.id]);
  const { agent, turns, send, isRunning, isReady, isLoadingHistory } = useAgentChat(threadId, "sangam_proposal", "proposal-chat", load);
  const [draft, setDraft] = useState("");
  const [failed, setFailed] = useState(false);
  const wasRunning = useRef(false);

  useAgentContext({ description: SCREEN, value: screen });

  // A turn may have saved or moved the step: read the proposal again.
  useEffect(() => {
    if (wasRunning.current && !isRunning) onTurnEnd();
    wasRunning.current = isRunning;
  }, [isRunning, onTurnEnd]);

  useEffect(() => {
    if (!agent) return;
    const sub = agent.subscribe({ onRunFailed: () => setFailed(true), onRunStartedEvent: () => setFailed(false) });
    return () => sub.unsubscribe();
  }, [agent]);

  const ready = isReady && !isLoadingHistory;

  async function submit() {
    const text = draft.trim();
    if (!text || isRunning) return;
    setDraft("");
    setFailed(false);
    await send(text);
  }

  return (
    <section className="card pr-side-card" aria-label="Ask Sangam">
      <div className="card-title">Ask Sangam</div>
      <p className="muted pr-chat-note">
        Only you see this chat. Sangam sees the step you are on, any text you select, and what your teammates change.
      </p>
      {turns.length === 0 ? (
        <p className="muted">{isLoadingHistory ? "Loading your chat…" : "Ask anything about this step."}</p>
      ) : (
        <div className="chat-turns pr-chat-turns">
          {turns.map((turn) => (
            <div key={turn.id} className="chat-turn">
              <div className="chat-question">
                <div aria-hidden className="chat-you">
                  Q
                </div>
                <div className="chat-question-text">{turn.question}</div>
              </div>
              <TraceCard steps={turn.steps} streaming={turn.streaming && !turn.answer} />
              {turn.answer && <AnswerCard answer={turn.answer} index={null} />}
            </div>
          ))}
        </div>
      )}
      {failed && (
        <p className="pr-stop" role="alert">
          Sangam could not answer. Try again in a moment.
        </p>
      )}
      <div className="pr-chat-composer">
        <textarea
          className="input pr-chat-input"
          placeholder="For example: what does the funder mean by this requirement?"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void submit();
          }}
          aria-label="Ask Sangam"
        />
        <button className="btn btn-primary" type="button" onClick={() => void submit()} disabled={!ready || isRunning || !draft.trim()}>
          {isRunning ? "Working…" : ready ? "Ask" : "Connecting…"}
        </button>
      </div>
    </section>
  );
}
