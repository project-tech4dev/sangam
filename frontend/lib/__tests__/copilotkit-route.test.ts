import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/auth-headers.server", () => ({ serverAuthHeaders: async () => ({}) }));

const { GET, POST } = await import("@/app/api/copilotkit/[[...slug]]/route");

// The installed runtime, built exactly as the route builds it, called with no cookie or Authorization.
const call = (handler: typeof GET, path: string, method = "GET", init: RequestInit = {}) =>
  handler(new Request(`http://localhost/api/copilotkit${path}`, { method, ...init }));

describe("/api/copilotkit", () => {
  it("serves info", async () => {
    expect((await call(GET, "/info")).status).toBe(200);
  });

  it.each([
    ["GET", "/threads"],
    ["GET", "/threads/t1/events"],
    ["GET", "/threads/t1/messages"],
    ["POST", "/threads/clear"],
  ])("404s %s %s", async (method, path) => {
    const handler = method === "GET" ? GET : POST;
    expect((await call(handler, path, method)).status).toBe(404);
  });

  it("401s a signed-out connect or stop", async () => {
    const body = JSON.stringify({ threadId: "t1", runId: "r1", messages: [], tools: [], context: [], state: {} });
    expect((await call(POST, "/agent/sangam_agent/connect", "POST", { body })).status).toBe(401);
    expect((await call(POST, "/agent/sangam_agent/stop/t1", "POST")).status).toBe(401);
  });

  it("asks the backend before a connect, and replays only for the owner", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(null, { status: 404 }));
    const body = JSON.stringify({ threadId: "t1", runId: "r1", messages: [], tools: [], context: [], state: {} });
    const headers = { authorization: "Bearer someone-else" };
    expect((await call(POST, "/agent/sangam_agent/connect", "POST", { body, headers })).status).toBe(404);
    expect(String(fetchSpy.mock.calls[0]![0])).toMatch(/\/api\/threads\/t1\/owned$/);

    fetchSpy.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const owner = await call(POST, "/agent/sangam_agent/connect", "POST", { body, headers });
    expect(owner.status).toBe(200);
    expect(owner.headers.get("content-type")).toContain("text/event-stream");
    fetchSpy.mockRestore();
  });
});
