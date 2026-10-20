import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PartnerGroup, PartnerGroupPage, PartnerLineRow } from "@/lib/api";
import { distinctLines, lineYear, usePartnerGroups } from "@/features/registry/profile/partnerGroups";

vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({ Authorization: "Bearer t" }) }));

const line = (over: Partial<PartnerLineRow> = {}) =>
  ({ fiscal_year: "FY2024", fy_is_dated: true, start_date: null, project_name: "Creches", program_name: null,
    amount: 100, relationship_status: null, ...over }) as PartnerLineRow;

describe("lineYear", () => {
  it("uses a dated fiscal year, else the start year, else nothing", () => {
    expect(lineYear(line())).toBe("FY2024");
    expect(lineYear(line({ fy_is_dated: false, start_date: "2022-04-01" }))).toBe("FY2022");
    expect(lineYear(line({ fy_is_dated: false }))).toBe("");
  });
});

describe("distinctLines", () => {
  it("shows two rows saying the same thing once", () => {
    const a = line({ id: 1 });
    const b = line({ id: 2 });
    const c = line({ id: 3, amount: 200 });
    const d = line({ id: 4, project_name: null, program_name: "Creches" });
    expect(distinctLines({ lines: [a, b, c, d] } as unknown as PartnerGroup)).toEqual([a, c]);
  });
});

describe("usePartnerGroups", () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });
  const group = (n: number) => ({ key: String(n) }) as unknown as PartnerGroup;

  it("appends the next page by cursor, then stops", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ groups: [group(2)], next_cursor: null }) });
    const { result } = renderHook(() => usePartnerGroups({ groups: [group(1)], next_cursor: "a b" } as PartnerGroupPage, "/api/funders/1/partners"));
    act(() => result.current.more());
    expect(result.current.busy).toBe(true);
    await waitFor(() => expect(result.current.groups).toHaveLength(2));
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8010/api/funders/1/partners?cursor=a%20b", {
      headers: { Authorization: "Bearer t" },
    });
    act(() => result.current.more());
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("reports a failed page without losing the groups", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500 });
    const { result } = renderHook(() => usePartnerGroups({ groups: [group(1)], next_cursor: "c" } as PartnerGroupPage, "/p"));
    act(() => result.current.more());
    await waitFor(() => expect(result.current.error).toBe(true));
    expect(result.current.busy).toBe(false);
    expect(result.current.groups).toHaveLength(1);
  });
});
