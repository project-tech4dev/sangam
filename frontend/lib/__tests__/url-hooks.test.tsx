import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setUrlParams } from "@/lib/url";
import { useUrlTab } from "@/lib/useUrlTab";
import { useUrlThread } from "@/lib/useUrlThread";
import { navigation } from "@/tests/setup";

afterEach(() => window.history.replaceState(null, "", "/"));

describe("setUrlParams", () => {
  it("pushes a screen change and replaces a fill-in", () => {
    const push = vi.spyOn(window.history, "pushState");
    const replace = vi.spyOn(window.history, "replaceState");
    setUrlParams({ view: "vault" });
    expect(push).toHaveBeenCalledWith(null, "", "http://localhost:3000/?view=vault");
    setUrlParams({ q: "tata" }, "replace");
    expect(replace).toHaveBeenCalledWith(null, "", "http://localhost:3000/?view=vault&q=tata");
    expect(window.location.search).toBe("?view=vault&q=tata");
    push.mockRestore();
    replace.mockRestore();
  });

  it("writes nothing when the address would not change", () => {
    const push = vi.spyOn(window.history, "pushState");
    setUrlParams({ view: null });
    expect(push).not.toHaveBeenCalled();
    push.mockRestore();
  });
});

describe("useUrlTab", () => {
  const tabs = ["mandate", "giving", "reach"];

  it("reads ?tab= and falls back to the first", () => {
    navigation.search = new URLSearchParams("tab=giving");
    expect(renderHook(() => useUrlTab(tabs)).result.current[0]).toBe("giving");
    navigation.search = new URLSearchParams("tab=bogus");
    expect(renderHook(() => useUrlTab(tabs)).result.current[0]).toBe("mandate");
  });

  it("keeps the first tab out of the address", () => {
    const { result } = renderHook(() => useUrlTab(tabs));
    act(() => result.current[1]("reach"));
    expect(window.location.search).toBe("?tab=reach");
    act(() => result.current[1]("mandate"));
    expect(window.location.search).toBe("");
  });
});

describe("useUrlThread", () => {
  const ids = () => {
    let n = 0;
    return vi.fn(() => `draft-${++n}`);
  };
  const valid = (id: string) => id.startsWith("t-") || id.startsWith("draft-");

  it("is an unsent draft with no thread in the address", () => {
    const { result } = renderHook(() => useUrlThread(ids(), { valid }));
    expect(result.current.threadId).toBe("draft-1");
    expect(result.current.resume).toBe(false);
  });

  it("resumes a valid thread from the address and ignores an invalid one", () => {
    navigation.search = new URLSearchParams("thread=t-9");
    expect(renderHook(() => useUrlThread(ids(), { valid })).result.current).toMatchObject({ threadId: "t-9", resume: true });
    navigation.search = new URLSearchParams("thread=../etc");
    expect(renderHook(() => useUrlThread(ids(), { valid })).result.current.threadId).toBe("draft-1");
  });

  it("names the draft in the address on its first send, without a Back step", () => {
    const push = vi.spyOn(window.history, "pushState");
    const { result } = renderHook(() => useUrlThread(ids(), { valid }));
    act(() => result.current.markSent());
    expect(window.location.search).toBe("?thread=draft-1");
    expect(push).not.toHaveBeenCalled();
    push.mockRestore();
  });

  it("starts a fresh draft once a sent one is left", () => {
    const newId = ids();
    const { result, rerender } = renderHook(() => useUrlThread(newId, { valid }));
    act(() => result.current.markSent());
    navigation.search = new URLSearchParams("thread=draft-1");
    rerender();
    expect(result.current.threadId).toBe("draft-1");
    navigation.search = new URLSearchParams("thread=t-5");
    rerender();
    navigation.search = new URLSearchParams();
    rerender();
    expect(result.current.threadId).toBe("draft-2");
  });

  it("renews to a new draft on request", () => {
    const { result } = renderHook(() => useUrlThread(ids(), { valid }));
    let id = "";
    act(() => {
      id = result.current.renew();
    });
    expect(id).toBe("draft-2");
    expect(result.current.threadId).toBe("draft-2");
  });
});
