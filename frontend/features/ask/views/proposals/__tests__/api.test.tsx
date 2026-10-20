import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/features/ask/lib/rest";

const call = vi.fn();
vi.mock("@/features/ask/lib/rest", async (original) => ({
  ...(await original<typeof import("@/features/ask/lib/rest")>()),
  call: (...args: unknown[]) => call(...args),
}));

// The proposal list is a module-level store, so each test starts from a fresh copy.
async function load() {
  vi.resetModules();
  return import("@/features/ask/views/proposals/api");
}

beforeEach(() => call.mockReset());
afterEach(() => {
  vi.useRealTimers();
  localStorage.clear();
});

describe("useProposals", () => {
  it("loads the list once and shares it", async () => {
    const api = await load();
    call.mockResolvedValue([{ id: 1 }]);
    const { result } = renderHook(() => api.useProposals());
    expect(result.current).toEqual([]);
    await waitFor(() => expect(result.current).toEqual([{ id: 1 }]));
    expect(call).toHaveBeenCalledWith("/api/proposals");
    renderHook(() => api.useProposals());
    expect(call).toHaveBeenCalledOnce();
  });

  it("keeps the last list when a reload fails", async () => {
    const api = await load();
    call.mockResolvedValueOnce([{ id: 1 }]);
    const { result } = renderHook(() => api.useProposals());
    await waitFor(() => expect(result.current).toEqual([{ id: 1 }]));
    call.mockRejectedValueOnce(new Error("down"));
    await act(() => api.reloadProposals());
    expect(result.current).toEqual([{ id: 1 }]);
  });
});

describe("proposal calls", () => {
  it("hit the right endpoints and refresh the list after a change", async () => {
    const api = await load();
    const isList = (path: string, method?: string) => path === "/api/proposals" && !method;
    call.mockImplementation(async (path: string, method?: string) =>
      isList(path, method) ? [] : String(path).endsWith("/file") ? { url: "https://f" } : { id: 5 });
    await expect(api.startProposal("kabil", 2, "Pitch")).resolves.toBe(5);
    await api.getProposal(5);
    await api.saveWork(5, { style: "plain" });
    await api.saveWork(5, { style: "plain" }, { B1: 2 });
    await api.rename(5, "New");
    await api.advance(5);
    await api.polishProposal(5);
    await api.saveVersion(5);
    await expect(api.versionLink(11)).resolves.toBe("https://f");
    const writes = call.mock.calls.filter(([path, method]) => !isList(path, method));
    expect(writes).toEqual([
      ["/api/proposals", "POST", { org: "kabil", funder_id: 2, title: "Pitch" }],
      ["/api/proposals/5"],
      ["/api/proposals/5/work", "PATCH", { set: { style: "plain" }, rev: {} }],
      ["/api/proposals/5/work", "PATCH", { set: { style: "plain" }, rev: { B1: 2 } }],
      ["/api/proposals/5", "PATCH", { title: "New" }],
      ["/api/proposals/5/advance", "POST"],
      ["/api/proposals/5/polish", "POST"],
      ["/api/proposals/5/versions", "POST"],
      ["/api/documents/11/file"],
    ]);
    // start, save twice, rename, advance and version each reload the list; polish does not.
    expect(call.mock.calls.filter(([path, method]) => isList(path, method))).toHaveLength(6);
  });

  it("reads the chat, and treats a missing one as empty", async () => {
    const api = await load();
    call.mockResolvedValueOnce({ messages: [{ id: "m" }] });
    await expect(api.fetchProposalMessages(1)).resolves.toEqual([{ id: "m" }]);
    call.mockRejectedValueOnce(new ApiError("nf", 404, null));
    await expect(api.fetchProposalMessages(1)).resolves.toEqual([]);
    call.mockRejectedValueOnce(new ApiError("no", 500, null));
    await expect(api.fetchProposalMessages(1)).rejects.toThrow("no");
  });
});

describe("reading a 409", () => {
  const conflict = (detail: unknown) => new ApiError("conflict", 409, { detail });

  it("ignores anything that is not a 409", async () => {
    const api = await load();
    for (const error of [new Error("x"), new ApiError("x", 500, {})]) {
      expect(api.differencesFrom(error)).toBeNull();
      expect(api.staleFrom(error)).toBeNull();
      expect(api.changedByLine(error)).toBeNull();
      expect(api.missingFrom(error)).toBeNull();
    }
  });

  it("pulls out differences, missing items and a stale part", async () => {
    const api = await load();
    expect(api.differencesFrom(conflict({ differences: ["₹5 lakh became ₹50 lakh"] }))).toEqual(["₹5 lakh became ₹50 lakh"]);
    expect(api.differencesFrom(conflict({}))).toBeNull();
    expect(api.missingFrom(conflict({ missing: ["CSR-1"] }))).toEqual(["CSR-1"]);
    expect(api.missingFrom(new ApiError("c", 409, null))).toBeNull();
    const by = { by: { id: "u", name: "Ravi" }, at: "2026-10-21T10:00:00Z" };
    expect(api.staleFrom(conflict({ section: "B1", current: { text: "new" }, changed_by: by }))).toEqual({ current: { text: "new" }, changed_by: by });
    expect(api.staleFrom(conflict({ section: "B1", current: { text: "new" } }))).toEqual({ current: { text: "new" }, changed_by: null });
    expect(api.staleFrom(conflict({ current: { text: "new" } }))).toBeNull();
  });

  it("says who changed a part and how long ago", async () => {
    const api = await load();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-21T10:00:00Z"));
    const line = (at: string) => api.changedByLine(conflict({ changed_by: { by: { id: "u", name: "Ravi" }, at } }));
    expect(line("2026-10-21T10:00:10Z")).toBe("Ravi changed this just now. Showing their version.");
    expect(line("2026-10-21T09:59:00Z")).toBe("Ravi changed this a minute ago. Showing their version.");
    expect(line("2026-10-21T09:45:00Z")).toBe("Ravi changed this 15 minutes ago. Showing their version.");
    expect(line("2026-10-21T08:00:00Z")).toBe("Ravi changed this earlier. Showing their version.");
    expect(api.changedByLine(conflict({}))).toBe("Someone changed this since you opened it. Showing the latest version.");
  });
});

describe("hadBrowserProposals", () => {
  it("is true only for a non-empty saved list", async () => {
    const api = await load();
    expect(api.hadBrowserProposals()).toBe(false);
    localStorage.setItem("sangam.proposals.v1", "[]");
    expect(api.hadBrowserProposals()).toBe(false);
    localStorage.setItem("sangam.proposals.v1", '[{"id":1}]');
    expect(api.hadBrowserProposals()).toBe(true);
    localStorage.setItem("sangam.proposals.v1", "{bad");
    expect(api.hadBrowserProposals()).toBe(false);
  });
});
