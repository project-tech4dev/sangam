"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAgent, useCopilotKit } from "@copilotkit/react-core/v2";
import type { Message } from "@ag-ui/client";

export type TraceStep = {
  id: string;
  tool: string;
  args: unknown;
  result: string | null; // null while running
  running: boolean;
};

export type Turn = {
  id: string;
  question: string;
  steps: TraceStep[];
  answer: string;
  streaming: boolean;
};

type AnyMessage = {
  id: string;
  role: string;
  content?: string;
  toolCallId?: string;
  toolCalls?: { id: string; type: string; function: { name: string; arguments: string } }[];
};

function safeParse(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

/** `loadHistory` fills a reopened chat with its saved messages; without it the chat starts empty. */
export function useAgentChat(
  threadId: string,
  runtimeAgentId: string,
  prefix: string,
  loadHistory?: () => Promise<Message[]>,
) {
  // Local agentId is per-thread (a thread is written onto a single agent instance);
  // runtimeAgentId picks the backend graph: sangam_agent or sangam_ingest.
  const { agent, isReady } = useAgent({
    agentId: `${prefix}-${threadId}`,
    runtimeAgentId,
    threadId,
    throttleMs: 80,
  });
  const { copilotkit } = useCopilotKit();

  const [isLoadingHistory, setLoadingHistory] = useState(Boolean(loadHistory));

  // Only once the registered agent is ready: messages set on the provisional one are dropped.
  useEffect(() => {
    if (!loadHistory || !isReady || !agent) return;
    let cancelled = false;
    (agent.messages.length > 0 ? Promise.resolve(null) : loadHistory())
      .then((history) => {
        if (!cancelled && history && agent.messages.length === 0) agent.setMessages(history);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoadingHistory(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agent, isReady, loadHistory]);

  const messages = (agent?.messages ?? []) as AnyMessage[];
  const isRunning = Boolean(agent?.isRunning);

  const turns: Turn[] = useMemo(() => {
    const toolResults = new Map<string, string>();
    for (const m of messages) {
      if (m.role === "tool" && m.toolCallId) toolResults.set(m.toolCallId, m.content ?? "");
    }
    const out: Turn[] = [];
    let current: Turn | null = null;
    for (const m of messages) {
      if (m.role === "user") {
        current = { id: m.id, question: m.content ?? "", steps: [], answer: "", streaming: false };
        out.push(current);
      } else if (m.role === "assistant" && current) {
        for (const tc of m.toolCalls ?? []) {
          const result = toolResults.get(tc.id) ?? null;
          current.steps.push({
            id: tc.id,
            tool: tc.function.name,
            args: safeParse(tc.function.arguments || "{}"),
            result,
            running: result === null && isRunning,
          });
        }
        if (m.content) current.answer += (current.answer ? "\n\n" : "") + m.content;
      }
    }
    if (out.length > 0 && isRunning) out[out.length - 1]!.streaming = true;
    return out;
  }, [messages, isRunning]);

  const send = useCallback(
    async (text: string) => {
      if (!agent || !text.trim()) return;
      agent.addMessage({ id: crypto.randomUUID(), role: "user", content: text.trim() });
      await copilotkit.runAgent({ agent });
    },
    [agent, copilotkit],
  );

  const stop = useCallback(() => {
    if (agent) copilotkit.stopAgent({ agent });
  }, [agent, copilotkit]);

  return { turns, send, stop, isRunning, isReady, isLoadingHistory };
}
