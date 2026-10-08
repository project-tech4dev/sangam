"use client";

import { useCallback } from "react";
import { useAgentChat } from "@/lib/useAgentChat";
import { fetchThreadMessages } from "./threads";

export type { TraceStep, Turn } from "@/lib/useAgentChat";

/** Ask Sangam's chat. `resume` loads a past chat's saved messages; a new chat has none to load. */
export function useSangamChat(threadId: string, resume = false) {
  const load = useCallback(() => fetchThreadMessages(threadId), [threadId]);
  return useAgentChat(threadId, "sangam_agent", "sangam-chat", resume ? load : undefined);
}
