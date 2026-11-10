import { describe, expect, it, vi } from "vitest";
import type { RouteInfo } from "@copilotkit/runtime/v2";
import { backendOwnerCheck, gateRoute, type OwnerCheck } from "@/lib/copilotkit-access";

const connect: RouteInfo = { method: "agent/connect", agentId: "sangam_ingest" };
const stop: RouteInfo = { method: "agent/stop", agentId: "sangam_agent", threadId: "t-stop" };
const signedIn = async () => "Bearer tok";
const signedOut = async () => undefined;

function connectRequest(body: unknown): Request {
  return new Request("http://localhost/api/copilotkit/agent/sangam_ingest/connect", {
    method: "POST",
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

async function outcome(
  route: RouteInfo,
  request: Request,
  auth: () => Promise<string | undefined>,
  isOwner: OwnerCheck,
): Promise<number | "through"> {
  try {
    await gateRoute(route, request, auth, isOwner);
    return "through";
  } catch (thrown) {
    return (thrown as Response).status;
  }
}

const plain = new Request("http://localhost/api/copilotkit/info");

describe("gateRoute", () => {
  it("lets info, run and suggest through without asking the backend", async () => {
    const isOwner = vi.fn<OwnerCheck>();
    const auth = vi.fn(signedOut);
    for (const route of [
      { method: "info" },
      { method: "agent/run", agentId: "sangam_agent" },
      { method: "agent/suggest", agentId: "sangam_agent" },
    ] satisfies RouteInfo[]) {
      expect(await outcome(route, plain, auth, isOwner)).toBe("through");
    }
    expect(isOwner).not.toHaveBeenCalled();
    expect(auth).not.toHaveBeenCalled();
  });

  it("still 404s the runtime's thread store", async () => {
    expect(await outcome({ method: "threads/list" }, plain, signedIn, vi.fn())).toBe(404);
  });

  it("asks about the thread in a connect body, and leaves the body for the runtime", async () => {
    const isOwner = vi.fn<OwnerCheck>(async () => 204);
    const request = connectRequest({ threadId: "import-1", runId: "r1" });
    expect(await outcome(connect, request, signedIn, isOwner)).toBe("through");
    expect(isOwner).toHaveBeenCalledWith("import-1", "Bearer tok");
    expect(await request.json()).toMatchObject({ threadId: "import-1" });
  });

  it("asks about the thread in a stop URL", async () => {
    const isOwner = vi.fn<OwnerCheck>(async () => 204);
    expect(await outcome(stop, plain, signedIn, isOwner)).toBe("through");
    expect(isOwner).toHaveBeenCalledWith("t-stop", "Bearer tok");
  });

  it.each([
    ["someone else's thread", 404, 404],
    ["a signed-out token", 401, 401],
    ["a backend error", 500, 404],
  ])("refuses connect and stop for %s", async (_label, backend, status) => {
    const isOwner: OwnerCheck = async () => backend;
    expect(await outcome(connect, connectRequest({ threadId: "t1" }), signedIn, isOwner)).toBe(status);
    expect(await outcome(stop, plain, signedIn, isOwner)).toBe(status);
  });

  it("refuses when the backend cannot be reached", async () => {
    const isOwner: OwnerCheck = async () => {
      throw new Error("ECONNREFUSED");
    };
    expect(await outcome(stop, plain, signedIn, isOwner)).toBe(404);
  });

  it("is 401 signed out, before asking the backend", async () => {
    const isOwner = vi.fn<OwnerCheck>();
    expect(await outcome(stop, plain, signedOut, isOwner)).toBe(401);
    expect(await outcome(connect, connectRequest({ threadId: "t1" }), signedOut, isOwner)).toBe(401);
    expect(isOwner).not.toHaveBeenCalled();
  });

  it.each([["not json"], [{ runId: "r1" }], [{ threadId: "" }], [{ threadId: 7 }], [null]])(
    "is 400 for a connect body with no thread id: %j",
    async (body) => {
      expect(await outcome(connect, connectRequest(body), signedIn, vi.fn())).toBe(400);
    },
  );
});

describe("backendOwnerCheck", () => {
  it("asks the backend's owned route with the caller's token", async () => {
    const fetchImpl = vi.fn(async () => new Response(null, { status: 204 }));
    const check = backendOwnerCheck("http://backend:8000", fetchImpl as unknown as typeof fetch);
    expect(await check("import-1/x", "Bearer tok")).toBe(204);
    expect(fetchImpl).toHaveBeenCalledWith("http://backend:8000/api/threads/import-1%2Fx/owned", {
      headers: { Authorization: "Bearer tok" },
      cache: "no-store",
    });
  });
});
