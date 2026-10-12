"use client";

import { INTERRUPT_EVENT_NAME } from "@copilotkit/react-core/v2";
import type { AbstractAgent } from "@ag-ui/client";
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
// The chat's own agent, not a lookup by id: before the runtime registers the thread, a lookup throws.
export function useRunPause(agent: AbstractAgent | undefined): string | null {
  const [tool, setTool] = useState<string | null>(null);
  useEffect(() => {
    if (!agent) return;
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
