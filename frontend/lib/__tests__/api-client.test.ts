import { afterEach, describe, expect, it, vi } from "vitest";

const serverAuthHeaders = vi.fn();
vi.mock("@/lib/api/auth-headers.server", () => ({ serverAuthHeaders: () => serverAuthHeaders() }));

const fetchMock = vi.fn();

// BASE and the cache policy are read at import, so each env needs a fresh module.
async function load(env: Record<string, string | undefined>) {
  vi.resetModules();
  for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v);
  vi.stubGlobal("fetch", fetchMock);
  return import("@/lib/api/client");
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
  serverAuthHeaders.mockReset();
});

describe("apiGet", () => {
  it("strips /agent from AGENT_URL and never caches a signed-in read", async () => {
    const { apiGet } = await load({ AGENT_URL: "https://api.x/agent", NODE_ENV: "production" });
    serverAuthHeaders.mockResolvedValue({ Authorization: "Bearer t" });
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ n: 1 }) });
    expect(await apiGet("/api/orgs")).toEqual({ n: 1 });
    expect(fetchMock).toHaveBeenCalledWith("https://api.x/api/orgs", { headers: { Authorization: "Bearer t" }, cache: "no-store" });
  });

  it("caches a signed-out read in production, keyed by the deploy", async () => {
    const { apiGet } = await load({ AGENT_URL: undefined, NEXT_PUBLIC_API_URL: "https://pub.x", NODE_ENV: "production", VERCEL_DEPLOYMENT_ID: "dpl_1" });
    serverAuthHeaders.mockResolvedValue({});
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => [] });
    await apiGet("/api/registry");
    expect(fetchMock).toHaveBeenCalledWith("https://pub.x/api/registry", {
      headers: { "x-sangam-build": "dpl_1" }, next: { revalidate: 300 },
    });
  });

  it("does not cache in development and defaults to the local backend", async () => {
    const { apiGet } = await load({ AGENT_URL: undefined, NEXT_PUBLIC_API_URL: undefined, NODE_ENV: "development" });
    serverAuthHeaders.mockResolvedValue({});
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => null });
    await apiGet("/health");
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8010/health", { headers: {}, cache: "no-store" });
  });

  it("throws NotFoundError on 404 and a plain error otherwise", async () => {
    const { apiGet, NotFoundError } = await load({ NODE_ENV: "development" });
    serverAuthHeaders.mockResolvedValue({});
    fetchMock.mockResolvedValueOnce({ ok: false, status: 404 });
    await expect(apiGet("/api/orgs/x")).rejects.toBeInstanceOf(NotFoundError);
    fetchMock.mockResolvedValueOnce({ ok: false, status: 503 });
    await expect(apiGet("/api/orgs")).rejects.toThrow("GET /api/orgs failed: 503");
  });
});
