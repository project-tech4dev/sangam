import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AbstractAgent } from "@ag-ui/client";

vi.mock("@copilotkit/react-core/v2", () => ({ INTERRUPT_EVENT_NAME: "on_interrupt" }));

import { useRunPause } from "../useRunPause";

type Handlers = Record<string, (params: unknown) => void>;

function fakeAgent() {
  const agent = { handlers: {} as Handlers, unsubscribe: vi.fn() };
  const subscribe = (h: Handlers) => {
    agent.handlers = h;
    return { unsubscribe: agent.unsubscribe };
  };
  return { agent, asAgent: { subscribe } as unknown as AbstractAgent };
}

describe("useRunPause", () => {
  it("is null without an agent", () => {
    expect(renderHook(() => useRunPause(undefined)).result.current).toBeNull();
  });

  it("names the tool an interrupt event stops on, and clears on a new run", () => {
    const { agent, asAgent } = fakeAgent();
    const { result, unmount } = renderHook(() => useRunPause(asAgent));
    const value = JSON.stringify({ action_requests: [{ name: "choose_sources" }] });
    act(() => agent.handlers.onCustomEvent!({ event: { name: "on_interrupt", value } }));
    expect(result.current).toBe("choose_sources");
    act(() => agent.handlers.onRunStartedEvent!({}));
    expect(result.current).toBeNull();
    act(() => agent.handlers.onCustomEvent!({ event: { name: "other", value } }));
    expect(result.current).toBeNull();
    unmount();
    expect(agent.unsubscribe).toHaveBeenCalledOnce();
  });

  it("reads an interrupted finish, and gives an empty name when it cannot tell", () => {
    const { agent, asAgent } = fakeAgent();
    const { result } = renderHook(() => useRunPause(asAgent));
    act(() => agent.handlers.onRunFinishedEvent!({ outcome: "interrupt", interrupts: [{ value: { action_requests: [{ name: "x" }] } }] }));
    expect(result.current).toBe("x");
    act(() => agent.handlers.onRunFailed!({}));
    expect(result.current).toBeNull();
    act(() => agent.handlers.onCustomEvent!({ event: { name: "on_interrupt", value: "{bad" } }));
    expect(result.current).toBe("");
    act(() => agent.handlers.onRunFinishedEvent!({ outcome: "success", interrupts: [] }));
    expect(result.current).toBe("");
  });
});
