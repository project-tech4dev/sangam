import { expect, it } from "vitest";
import { DEFAULTS, filterParams, filtersFrom, registryQuery } from "@/features/registry/filtersUrl";

it("reads an empty address as every default", () => {
  expect(filtersFrom(new URLSearchParams())).toEqual({ kind: "all", ...DEFAULTS });
});

it("writes only the params that changed, and clears the bucket for all", () => {
  expect(filterParams({ kind: "org", q: "" })).toEqual({ type: "cso", q: null });
  expect(filterParams({ kind: "all", sdg: "4" })).toEqual({ type: null, sdg: "4" });
});

it("asks the API with the address's names, a trimmed search, and the page", () => {
  const q = registryQuery({ kind: "org", ...DEFAULTS, where: "ne", q: "  dalgu " }, 25, 25);
  expect(Object.fromEntries(new URLSearchParams(q))).toEqual({ type: "cso", where: "ne", q: "dalgu", limit: "25", offset: "25" });
  expect(registryQuery({ kind: "all", ...DEFAULTS }, 0, 25)).toBe("limit=25&offset=0");
});
