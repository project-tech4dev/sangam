"use client";

import { INTERRUPT_EVENT_NAME, useAgent } from "@copilotkit/react-core/v2";
import { useEffect, useState } from "react";

const named = (value: unknown): string => {
  let request = value;
  if (typeof request === "string") {
    try {
      request = JSON.parse(request);
    } catch {
      return "";
    }
  }
  return (request as { action_requests?: { name?: string }[] } | null)?.action_requests?.[0]?.name ?? "";
};

/** The tool the last run stopped on to wait for a person ("" if unnamed), or null when it did not stop. */
export function useRunPause(agentId: string): string | null {
  const { agent } = useAgent({ agentId, updates: [] });
  const [tool, setTool] = useState<string | null>(null);
  useEffect(() => {
    const subscription = agent.subscribe({
      onCustomEvent: ({ event }) => {
        if (event.name === INTERRUPT_EVENT_NAME) setTool(named(event.value));
      },
      onRunFinishedEvent: (params) => {
        if (params.outcome === "interrupt") setTool(named((params.interrupts[0] as { value?: unknown })?.value));
      },
      onRunStartedEvent: () => setTool(null),
      onRunFailed: () => setTool(null),
    });
    return () => subscription.unsubscribe();
  }, [agent]);
  return tool;
}
