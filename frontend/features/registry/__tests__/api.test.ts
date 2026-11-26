import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({}) }));

import { fetchTracked } from "../api";

afterEach(() => vi.unstubAllGlobals());

describe("fetchTracked", () => {
  it("returns what the backend lists", async () => {
    const row = { slug: "kabil", kind: "org", id: 1, sources: 4, last_checked: null };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => [row] }) as Response));
    expect(await fetchTracked()).toEqual([row]);
  });

  it("is an empty list when the backend refuses, so the Registry still shows", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 403, json: async () => ({ detail: "Staff only" }) }) as Response));
    expect(await fetchTracked()).toEqual([]);
  });
});
