import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RegistryIndex } from "@/features/ask/lib/citations";

const call = vi.fn<(path: string) => Promise<unknown>>();
vi.mock("@/lib/api/rest", () => ({ call: (path: string) => call(path) }));

import { useCitedIndex } from "@/features/ask/lib/useCitedIndex";

afterEach(() => vi.clearAllMocks());

const base = (): RegistryIndex => ({
  orgs: new Map([[1, { slug: "kabil", name: "KABIL" }]]),
  funders: new Map([[29, { slug: "axis-bank-foundation", name: "Axis Bank Foundation" }]]),
  scores: new Map(),
  activities: new Map(),
});

const org = { id: 812, slug: "gramya", name: "GRAMYA VIKASH MANCH", source_url: null, source_name: "darpan-portal", fetched_at: null };
const score = { id: 40, org_id: 812, org_name: "Gramya", funder_id: 29, funder_name: "Axis Bank Foundation", rubric_version: "match-v2" };
const line = { id: 77, funder_id: 29, funder_slug: "axis-bank-foundation", funder_name: "Axis Bank Foundation",
  partner_name: "Gramya", partner_org_slug: "gramya", project_name: null, source_url: null, source_name: null, fetched_at: null };

describe("useCitedIndex", () => {
  it("looks up only the cited rows the page lacks, and names them", async () => {
    call.mockImplementation(async (path) =>
      path.startsWith("/api/orgs") ? [org] : path.startsWith("/api/scores") ? { items: [score] } : { items: [line] },
    );
    const { result } = renderHook(() => useCitedIndex(base()));
    act(() => result.current[1]("KABIL [org:1] and Gramya [org:812] [score:40] [activity:77] [funder:29]"));

    await waitFor(() => expect(result.current[0].orgs.get(812)?.name).toBe("Gramya Vikash Manch"));
    expect(call.mock.calls.map(([p]) => p)).toEqual([
      "/api/orgs?ids=812",
      "/api/scores?limit=100&ids=40",
      "/api/partner-lines?limit=100&ids=77",
    ]);
    expect(result.current[0].scores.get(40)).toMatchObject({ funderSlug: "axis-bank-foundation", orgName: "Gramya" });
    expect(result.current[0].activities.get(77)).toMatchObject({ short: "Axis Bank Foundation → Gramya", href: "/registry/gramya" });
  });

  it("asks once per row, and a failed lookup leaves the index as it was", async () => {
    call.mockRejectedValue(new Error("500"));
    const { result } = renderHook(() => useCitedIndex(base()));
    act(() => result.current[1]("[org:900]"));
    await waitFor(() => expect(call).toHaveBeenCalledTimes(1));
    act(() => result.current[1]("[org:900] again"));
    expect(call).toHaveBeenCalledTimes(1);
    expect(result.current[0].orgs.has(900)).toBe(false);
  });

  it("asks nothing when the page already holds every cited row", () => {
    const { result } = renderHook(() => useCitedIndex(base()));
    act(() => result.current[1]("KABIL [org:1] [funder:29] [news:3]"));
    expect(call).not.toHaveBeenCalled();
  });
});
