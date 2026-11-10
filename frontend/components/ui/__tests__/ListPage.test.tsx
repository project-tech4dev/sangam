import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { BucketCards, FilterRow, ListMore, SearchBox, useCursorList, usePagedList, useShowMore } from "@/components/ui/ListPage";

describe("BucketCards", () => {
  const items = [
    { key: "all", label: "All", count: 12 },
    { key: "org", label: "Organisations", count: 8, sub: "in the cohort" },
  ] as const;

  it("marks the active bucket and reports a pick", async () => {
    const onPick = vi.fn();
    render(<BucketCards items={[...items]} active="all" onPick={onPick} label="Kind" />);
    expect(screen.getByRole("group", { name: "Kind" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /All/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Organisations/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("in the cohort")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Organisations/ }));
    expect(onPick).toHaveBeenCalledWith("org");
  });
});

describe("FilterRow", () => {
  it("renders nothing with no filters", () => {
    const { container } = render(<FilterRow filters={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("flags a moved filter and reports the new value", async () => {
    const onChange = vi.fn();
    render(
      <FilterRow
        filters={[
          { key: "theme", label: "Theme", value: "all", defaultValue: "all", options: [["all", "Any theme"], ["health", "Health"]], onChange },
          { key: "where", label: "Where", value: "ne", defaultValue: "all", options: [["all", "Anywhere"], ["ne", "North-east"]], onChange: vi.fn() },
        ]}
      />,
    );
    const theme = screen.getByRole("combobox", { name: "Theme" });
    expect(theme).toHaveAttribute("data-set", "false");
    expect(screen.getByRole("combobox", { name: "Where" })).toHaveAttribute("data-set", "true");
    await userEvent.selectOptions(theme, "health");
    expect(onChange).toHaveBeenCalledWith("health");
  });
});

describe("SearchBox", () => {
  it("calls onChange with the typed text", async () => {
    const onChange = vi.fn();
    render(<SearchBox value="" onChange={onChange} placeholder="Search funders" />);
    await userEvent.type(screen.getByRole("searchbox", { name: "Search funders" }), "t");
    expect(onChange).toHaveBeenCalledWith("t");
  });
});

describe("useShowMore", () => {
  it("grows by a page and resets when the key changes", () => {
    const { result, rerender } = renderHook(({ k }) => useShowMore(k, 5), { initialProps: { k: "a" } });
    expect(result.current[0]).toBe(5);
    act(() => result.current[1]());
    expect(result.current[0]).toBe(10);
    rerender({ k: "b" });
    expect(result.current[0]).toBe(5);
  });
});

describe("ListMore", () => {
  it("is empty with no rows and says when the list has ended", () => {
    const { container, rerender } = render(<ListMore shown={0} total={0} onMore={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<ListMore shown={5} total={5} onMore={vi.fn()} />);
    expect(screen.getByText("End of the list")).toBeInTheDocument();
  });

  it("offers at most a page more and loads on click", async () => {
    const onMore = vi.fn();
    const { rerender } = render(<ListMore shown={10} total={13} onMore={onMore} />);
    await userEvent.click(screen.getByRole("button", { name: "Show 3 more · 3 left" }));
    expect(onMore).toHaveBeenCalledOnce();
    rerender(<ListMore shown={10} total={40} onMore={onMore} />);
    expect(screen.getByRole("button", { name: "Show 10 more · 30 left" })).toBeEnabled();
    rerender(<ListMore shown={10} total={40} onMore={onMore} busy />);
    expect(screen.getByRole("button", { name: "Loading…" })).toBeDisabled();
  });

  it("loads near the end only after the person has scrolled", () => {
    let fire: (hit: boolean) => void = () => {};
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(cb: (e: { isIntersecting: boolean }[]) => void) {
          fire = (hit) => cb([{ isIntersecting: hit }]);
        }
        observe() {}
        disconnect() {}
      },
    );
    const onMore = vi.fn();
    render(<ListMore shown={10} total={30} onMore={onMore} />);
    fire(true);
    expect(onMore).not.toHaveBeenCalled();
    document.dispatchEvent(new Event("scroll"));
    fire(false);
    expect(onMore).not.toHaveBeenCalled();
    fire(true);
    expect(onMore).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });
});

describe("useCursorList", () => {
  type Page = { items: { id: number }[]; next_cursor: string | null };

  it("pages through the cursor without repeating a row", async () => {
    const load = vi.fn(async (cursor: string | null): Promise<Page> =>
      cursor ? { items: [{ id: 2 }, { id: 3 }], next_cursor: null } : { items: [{ id: 1 }, { id: 2 }], next_cursor: "c1" },
    );
    const { result } = renderHook(() => useCursorList<{ id: number }, Page>("k", load, (i) => i.id));
    expect(result.current.busy).toBe(true);
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(result.current.items.map((i) => i.id)).toEqual([1, 2]);
    act(() => result.current.more!());
    await waitFor(() => expect(result.current.items.map((i) => i.id)).toEqual([1, 2, 3]));
    expect(result.current.more).toBeNull();
    expect(load).toHaveBeenLastCalledWith("c1");
    act(() => result.current.remove((i) => i.id !== 2));
    expect(result.current.items.map((i) => i.id)).toEqual([1, 3]);
  });

  it("keeps the rows and reports the error when a page fails", async () => {
    const { result } = renderHook(() =>
      useCursorList<{ id: number }, Page>("k", () => Promise.reject(new Error("boom")), (i) => i.id),
    );
    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.items).toEqual([]);
  });

  it("does not keep the last key's page when the first page of a new key fails", async () => {
    const { result, rerender } = renderHook(
      ({ k }) => useCursorList<{ id: number }, Page>(k, (): Promise<Page> =>
        k === "a" ? Promise.resolve({ items: [{ id: 1 }], next_cursor: "c" }) : Promise.reject(new Error("boom")), (i) => i.id),
      { initialProps: { k: "a" } },
    );
    await waitFor(() => expect(result.current.last).not.toBeNull());
    rerender({ k: "b" });
    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.last).toBeNull();
  });

  it("drops an answer for a key that is no longer current", async () => {
    let resolveA: (p: Page) => void = () => {};
    const load = vi.fn((cursor: string | null) => {
      void cursor;
      return new Promise<Page>((r) => (resolveA = r));
    });
    const { result, rerender } = renderHook(({ k }) => useCursorList<{ id: number }, Page>(k, load, (i) => i.id), {
      initialProps: { k: "a" },
    });
    const first = resolveA;
    rerender({ k: "b" });
    await act(async () => first({ items: [{ id: 9 }], next_cursor: null }));
    expect(result.current.items).toEqual([]);
    await act(async () => resolveA({ items: [{ id: 4 }], next_cursor: null }));
    expect(result.current.items).toEqual([{ id: 4 }]);
  });
});

describe("usePagedList", () => {
  type Page = { items: { id: number }[]; total: number };
  const ids = (items: { id: number }[]) => items.map((i) => i.id);

  it("loads from offset 0, then the next offset, until the total is shown", async () => {
    const load = vi.fn(async (offset: number): Promise<Page> =>
      offset === 0 ? { items: [{ id: 1 }, { id: 2 }], total: 3 } : { items: [{ id: 3 }], total: 3 },
    );
    const { result } = renderHook(() => usePagedList<{ id: number }, Page>("k", load, (i) => i.id, { limit: 2 }));
    expect(result.current.busy).toBe(true);
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(ids(result.current.items)).toEqual([1, 2]);
    expect(result.current.total).toBe(3);
    expect(load).toHaveBeenLastCalledWith(0, 2);
    act(() => result.current.more!());
    await waitFor(() => expect(ids(result.current.items)).toEqual([1, 2, 3]));
    expect(load).toHaveBeenLastCalledWith(2, 2);
    expect(result.current.more).toBeNull();
  });

  it("uses the server-rendered first page without fetching it again", async () => {
    const load = vi.fn(async (): Promise<Page> => ({ items: [{ id: 3 }], total: 3 }));
    const first = { items: [{ id: 1 }, { id: 2 }], total: 3 };
    const { result } = renderHook(() => usePagedList<{ id: number }, Page>("k", load, (i) => i.id, { limit: 2, first }));
    expect(result.current.busy).toBe(false);
    expect(ids(result.current.items)).toEqual([1, 2]);
    expect(result.current.last).toBe(first);
    expect(load).not.toHaveBeenCalled();
    act(() => result.current.more!());
    await waitFor(() => expect(ids(result.current.items)).toEqual([1, 2, 3]));
    expect(load).toHaveBeenCalledWith(2, 2);
  });

  it("starts again from offset 0 when the key changes, dropping the old key's answer", async () => {
    const pending: Record<string, (p: Page) => void> = {};
    const load = (key: string) => () => new Promise<Page>((r) => (pending[key] = r));
    const { result, rerender } = renderHook(
      ({ k }) => usePagedList<{ id: number }, Page>(k, load(k), (i) => i.id),
      { initialProps: { k: "a" } },
    );
    rerender({ k: "b" });
    await act(async () => pending.a({ items: [{ id: 9 }], total: 1 }));
    expect(result.current.items).toEqual([]);
    await act(async () => pending.b({ items: [{ id: 4 }], total: 1 }));
    expect(ids(result.current.items)).toEqual([4]);
  });

  it("does not show a row twice when the list shifted between pages", async () => {
    const load = vi.fn(async (offset: number): Promise<Page> =>
      offset === 0 ? { items: [{ id: 1 }, { id: 2 }], total: 4 } : { items: [{ id: 2 }, { id: 3 }], total: 4 },
    );
    const { result } = renderHook(() => usePagedList<{ id: number }, Page>("k", load, (i) => i.id, { limit: 2 }));
    await waitFor(() => expect(result.current.busy).toBe(false));
    act(() => result.current.more!());
    await waitFor(() => expect(ids(result.current.items)).toEqual([1, 2, 3]));
    expect(result.current.more).toBeNull(); // both pages fetched: offset 4 of 4
    expect(result.current.fetched).toBe(4); // so ListMore says "End of the list", not "1 left"
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("does not keep the last key's total when the first page of a new key fails", async () => {
    const { result, rerender } = renderHook(
      ({ k }) => usePagedList<{ id: number }, Page>(k, (): Promise<Page> =>
        k === "all" ? Promise.resolve({ items: [{ id: 1 }], total: 120 }) : Promise.reject(new Error("boom")), (i) => i.id),
      { initialProps: { k: "all" } },
    );
    await waitFor(() => expect(result.current.total).toBe(120));
    rerender({ k: "health" });
    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.total).toBe(0);
    expect(result.current.last).toBeNull();
    expect(result.current.more).toBeNull();
  });

  it("keeps the rows and reports the error when a page fails", async () => {
    const { result } = renderHook(() =>
      usePagedList<{ id: number }, Page>("k", () => Promise.reject(new Error("boom")), (i) => i.id),
    );
    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.items).toEqual([]);
  });
});
