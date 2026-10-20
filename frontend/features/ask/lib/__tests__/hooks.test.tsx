import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const getMe = vi.fn();
vi.mock("@/features/ask/lib/rest", () => ({ getMe: () => getMe() }));
const useAgentChat = vi.fn<(...args: unknown[]) => string>(() => "chat");
vi.mock("@/lib/useAgentChat", () => ({ useAgentChat: (...args: unknown[]) => useAgentChat(...args) }));
const fetchThreadMessages = vi.fn<(id: string) => Promise<unknown[]>>(async () => []);
vi.mock("@/features/ask/lib/threads", () => ({ fetchThreadMessages: (id: string) => fetchThreadMessages(id) }));

import { useOrgChoices } from "@/features/ask/lib/useOrgChoices";
import { useSangamChat } from "@/features/ask/lib/useSangamChat";

afterEach(() => vi.clearAllMocks());

const orgs = [{ slug: "kabil", name: "KABIL" }, { slug: "x", name: "X" }];

describe("useOrgChoices", () => {
  it("gives staff every organisation", async () => {
    getMe.mockResolvedValue({ is_staff: true, memberships: [] });
    const { result } = renderHook(() => useOrgChoices(orgs));
    expect(result.current.choices).toEqual([]);
    await waitFor(() => expect(result.current.choices).toEqual(orgs));
  });

  it("gives everyone else only their memberships", async () => {
    getMe.mockResolvedValue({ is_staff: false, memberships: [{ org_slug: "x", org_name: "X", org_id: 2, role: "member" }] });
    const { result } = renderHook(() => useOrgChoices(orgs));
    await waitFor(() => expect(result.current.choices).toEqual([{ slug: "x", name: "X" }]));
  });

  it("reports a failed lookup", async () => {
    getMe.mockRejectedValue(new Error("401"));
    const { result } = renderHook(() => useOrgChoices(orgs));
    await waitFor(() => expect(result.current.problem).toBe("401"));
    expect(result.current.me).toBeNull();
  });
});

describe("useSangamChat", () => {
  it("loads saved messages only when resuming", async () => {
    renderHook(() => useSangamChat("t1"));
    expect(useAgentChat).toHaveBeenLastCalledWith("t1", "sangam_agent", "sangam-chat", undefined);
    renderHook(() => useSangamChat("t2", true));
    const load = useAgentChat.mock.lastCall![3] as () => Promise<unknown>;
    await load();
    expect(fetchThreadMessages).toHaveBeenCalledWith("t2");
  });
});
