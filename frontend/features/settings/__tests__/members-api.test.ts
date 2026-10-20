import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { membersRequest } from "@/features/settings/members-api";

vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({ Authorization: "Bearer t" }) }));

describe("membersRequest", () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("lists members with a GET and no body", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => [{ user_id: "u" }] });
    expect(await membersRequest(7)).toEqual({ members: [{ user_id: "u" }] });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8010/api/orgs/7/members", {
      method: "GET", headers: { Authorization: "Bearer t", "Content-Type": "application/json" }, body: undefined,
    });
  });

  it("sends a JSON body for a change", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => [] });
    await membersRequest(7, "PATCH", "/u1", { role: "admin" });
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8010/api/orgs/7/members/u1");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "PATCH", body: '{"role":"admin"}' });
  });

  it("passes the server's message on, or a generic one", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, json: async () => ({ detail: "Not an admin." }) });
    expect(await membersRequest(7)).toEqual({ error: "Not an admin." });
    fetchMock.mockResolvedValueOnce({ ok: false, json: async () => ({ detail: [{ msg: "x" }] }) });
    expect(await membersRequest(7)).toEqual({ error: "Something went wrong." });
  });

  it("says Sangam is unreachable when the request throws", async () => {
    fetchMock.mockRejectedValue(new TypeError("network"));
    expect(await membersRequest(7)).toEqual({ error: "Could not reach Sangam. Try again." });
  });
});
