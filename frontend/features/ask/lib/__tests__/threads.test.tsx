import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({ Authorization: "Bearer t" }) }));

import { fetchThreadMessages, fetchThreads, loadThreads, saveThread, titleFrom } from "@/features/ask/lib/threads";

const fetchMock = vi.fn();
const reply = (status: number, body: unknown = {}) =>
  fetchMock.mockResolvedValueOnce({ ok: status < 400, status, json: async () => body });

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("local thread list", () => {
  it("keeps the newest first, replaces a re-saved chat and caps at fifty", () => {
    saveThread({ id: "a", title: "A", createdAt: 1 });
    saveThread({ id: "b", title: "B", createdAt: 2 });
    saveThread({ id: "a", title: "A2", createdAt: 3 });
    expect(loadThreads().map((t) => t.title)).toEqual(["A2", "B"]);
    for (let i = 0; i < 60; i++) saveThread({ id: `x${i}`, title: "", createdAt: i });
    expect(loadThreads()).toHaveLength(50);
  });

  it("reads corrupt storage as empty", () => {
    localStorage.setItem("sangam_threads_v1", "{nope");
    expect(loadThreads()).toEqual([]);
  });
});

describe("titleFrom", () => {
  it("collapses whitespace and cuts long questions at 56 characters", () => {
    expect(titleFrom("  Which   funders\nback health?  ")).toBe("Which funders back health?");
    expect(titleFrom("x".repeat(60))).toBe(`${"x".repeat(56)}…`);
  });
});

describe("fetchThreads", () => {
  it("uses server titles, falls back to local ones, and keeps a new active chat listed", async () => {
    saveThread({ id: "old", title: "Local title", createdAt: 1 });
    saveThread({ id: "new", title: "Just asked", createdAt: 5 });
    reply(200, [
      { thread_id: "s1", title: "Server title", created_at: "2026-10-01T00:00:00Z", updated_at: "" },
      { thread_id: "old", title: null, created_at: "2026-09-01T00:00:00Z", updated_at: "" },
      { thread_id: "gone", title: null, created_at: "2026-08-01T00:00:00Z", updated_at: "" },
    ]);
    const threads = await fetchThreads("new");
    expect(threads.map((t) => [t.id, t.title])).toEqual([
      ["new", "Just asked"],
      ["s1", "Server title"],
      ["old", "Local title"],
      ["gone", "Untitled chat"],
    ]);
    expect(threads[1]!.createdAt).toBe(Date.parse("2026-10-01T00:00:00Z"));
    expect(fetchMock.mock.calls[0]![1]).toEqual({ headers: { Authorization: "Bearer t" }, cache: "no-store" });
  });

  it("throws when the server refuses", async () => {
    reply(500);
    await expect(fetchThreads("x")).rejects.toThrow("Could not load chats (500).");
  });
});

describe("fetchThreadMessages", () => {
  it("returns the messages, none for an unsaved chat, and throws otherwise", async () => {
    reply(200, { messages: [{ id: "m1" }] });
    await expect(fetchThreadMessages("a/b")).resolves.toEqual([{ id: "m1" }]);
    expect(fetchMock.mock.calls[0]![0]).toMatch(/\/api\/threads\/a%2Fb\/messages$/);
    reply(404);
    await expect(fetchThreadMessages("a")).resolves.toEqual([]);
    reply(500);
    await expect(fetchThreadMessages("a")).rejects.toThrow("Could not load this chat (500).");
  });
});
