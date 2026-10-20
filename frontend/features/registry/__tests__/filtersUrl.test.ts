import { expect, it } from "vitest";
import { DEFAULTS, filterParams, filtersFrom } from "@/features/registry/filtersUrl";

it("reads an empty address as every default", () => {
  expect(filtersFrom(new URLSearchParams())).toEqual({ kind: "all", ...DEFAULTS });
});

it("writes only the params that changed, and clears the bucket for all", () => {
  expect(filterParams({ kind: "org", q: "" })).toEqual({ type: "cso", q: null });
  expect(filterParams({ kind: "all", sdg: "4" })).toEqual({ type: null, sdg: "4" });
});
