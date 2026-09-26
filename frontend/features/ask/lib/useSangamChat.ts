"use client";

import { useCallback, useMemo } from "react";
import { useAgent, useCopilotKit } from "@copilotkit/react-core/v2";

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

export function useSangamChat(threadId: string) {
  // Local agentId is per-thread (a thread is written onto a single agent
  // instance); runtimeAgentId routes to the backend LangGraph agent.
  const { agent, isReady } = useAgent({
    agentId: `sangam-chat-${threadId}`,
    runtimeAgentId: "sangam_agent",
    threadId,
    throttleMs: 80,
  });
  const { copilotkit } = useCopilotKit();

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

  return { turns, send, isRunning, isReady };
}
