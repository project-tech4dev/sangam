import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({ Authorization: "Bearer t" }) }));

import { API, ApiError, call, getMe } from "@/features/ask/lib/rest";
import { getDetail, getMatches, runMatch } from "@/features/ask/views/funder-match/api";
import { getFeed, setStatus } from "@/features/ask/views/rfp-watch/api";

const fetchMock = vi.fn();
const reply = (status: number, body: unknown) =>
  fetchMock.mockResolvedValueOnce({ ok: status < 400, status, json: async () => body });

beforeEach(() => vi.stubGlobal("fetch", fetchMock));
afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("call", () => {
  it("GETs with auth and no body", async () => {
    reply(200, { is_staff: true });
    await expect(getMe()).resolves.toEqual({ is_staff: true });
    expect(fetchMock).toHaveBeenCalledWith(`${API}/api/me`, { method: "GET", headers: { Authorization: "Bearer t" }, body: undefined });
  });

  it("sends a JSON body with its content type", async () => {
    reply(200, { ok: 1 });
    await call("/api/x", "POST", { a: 1 });
    expect(fetchMock).toHaveBeenCalledWith(`${API}/api/x`, {
      method: "POST",
      headers: { Authorization: "Bearer t", "Content-Type": "application/json" },
      body: '{"a":1}',
    });
  });

  it("raises the backend's detail with status and body", async () => {
    reply(409, { detail: "taken" });
    const error = await call("/api/x").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ message: "taken", status: 409, body: { detail: "taken" } });
  });

  it("falls back to the status when the body is not JSON", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 502, json: async () => { throw new Error("html"); } });
    await expect(call("/api/x")).rejects.toMatchObject({ message: "Request failed: 502", status: 502, body: null });
  });
});

describe("Funder Match and RFP Watch endpoints", () => {
  it("encode the org and use the right verbs", async () => {
    for (let i = 0; i < 5; i++) reply(200, {});
    await getMatches("a b");
    await getDetail(7);
    await runMatch("kabil&x");
    await getFeed("kabil");
    await setStatus(3, 4, "saved");
    const calls = fetchMock.mock.calls.map(([url, init]) => [url.replace(API, ""), init.method, init.body]);
    expect(calls).toEqual([
      ["/api/funder-matches?org=a%20b", "GET", undefined],
      ["/api/funder-matches/7/detail", "GET", undefined],
      ["/api/funder-matches/runs?org=kabil%26x", "POST", undefined],
      ["/api/rfps/feed?org=kabil", "GET", undefined],
      ["/api/rfps/3/matches/4", "PATCH", '{"status":"saved"}'],
    ]);
  });
});
