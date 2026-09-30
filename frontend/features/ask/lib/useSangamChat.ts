"use client";

import { useAgentChat } from "@/lib/useAgentChat";

export type { TraceStep, Turn } from "@/lib/useAgentChat";

/** Ask Sangam's chat. Sangam Import uses the same hook against its own graph. */
export function useSangamChat(threadId: string) {
  return useAgentChat(threadId, "sangam_agent", "sangam-chat");
}
