import { describe, expect, it } from "vitest";
import type { RouteInfo } from "@copilotkit/runtime/v2";
import { allowRoute } from "@/lib/copilotkit-access";

function status(route: RouteInfo): number | "served" {
  try {
    allowRoute(route);
    return "served";
  } catch (thrown) {
    return (thrown as Response).status;
  }
}

describe("allowRoute", () => {
  it.each<RouteInfo>([
    { method: "info" },
    { method: "agent/run", agentId: "sangam_agent" },
    { method: "agent/connect", agentId: "sangam_ingest" },
    { method: "agent/stop", agentId: "sangam_agent", threadId: "t1" },
    { method: "agent/suggest", agentId: "sangam_proposal" },
  ])("serves $method, which the chat client calls", (route) => {
    expect(status(route)).toBe("served");
  });

  it.each<RouteInfo>([
    { method: "threads/list" },
    { method: "threads/subscribe" },
    { method: "threads/events", threadId: "t1" },
    { method: "threads/messages", threadId: "t1" },
    { method: "threads/state", threadId: "t1" },
    { method: "threads/update", threadId: "t1" },
    { method: "threads/archive", threadId: "t1" },
    { method: "threads/clear" },
    { method: "memories/list" },
    { method: "memories/mutate", memoryId: "m1" },
    { method: "inspector/metadata" },
    { method: "inspector/learning" },
    { method: "transcribe" },
    { method: "annotate" },
    { method: "cpk-debug-events" },
  ])("404s $method, which would hand out other users' runs", (route) => {
    expect(status(route)).toBe(404);
  });
});
