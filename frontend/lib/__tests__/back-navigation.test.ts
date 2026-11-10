// Back returns to the previous screen only because each screen round-trips through its URL; these pin that.
import { expect, test } from "vitest";
import { idParam, oneOf, withParams } from "@/lib/url";
import { isAskThreadId, viewFrom, viewParams, WORKSPACE_VIEWS } from "@/features/ask/lib/workspaceUrl";
import { DEFAULTS, filterParams, filtersFrom, type Filters } from "@/features/registry/filtersUrl";

const params = (href: string) => new URL(href, "http://x").searchParams;

test("withParams sets, replaces and drops params, leaving the rest", () => {
  const href = "http://x/ask?view=proposals&proposal=4&thread=t";
  expect(withParams(href, { proposal: null })).toBe("http://x/ask?view=proposals&thread=t");
  expect(withParams(href, { proposal: "9" })).toBe("http://x/ask?view=proposals&proposal=9&thread=t");
  expect(withParams(href, { view: "", proposal: undefined })).toBe("http://x/ask?thread=t");
});

test("idParam accepts only positive integers", () => {
  expect(idParam("12")).toBe(12);
  for (const bad of [null, "", "0", "-3", "1.5", "abc", "12abc"]) expect(idParam(bad), String(bad)).toBe(null);
});

test("oneOf falls back to the first id", () => {
  const tabs = ["mandate", "giving", "reach"] as const;
  expect(oneOf("giving", tabs)).toBe("giving");
  expect(oneOf(null, tabs)).toBe("mandate");
  expect(oneOf("nope", tabs)).toBe("mandate");
});

test("every workspace view round-trips through the address", () => {
  for (const view of WORKSPACE_VIEWS) {
    const href = withParams("http://x/ask", viewParams(view));
    expect(viewFrom(params(href).get("view"))).toBe(view);
  }
  expect(viewFrom(null)).toBe("ask");
  expect(viewFrom("import")).toBe("ask");
});

test("a sidebar pick clears the last screen's ids but keeps the open chat", () => {
  const href = withParams("http://x/ask?view=proposals&proposal=4&funder=2&org=kabil&thread=t", viewParams("vault"));
  expect(href).toBe("http://x/ask?view=vault&thread=t");
  expect(withParams(href, viewParams("ask"))).toBe("http://x/ask?thread=t");
});

test("only a UUID is taken as an Ask thread from the address", () => {
  expect(isAskThreadId("0b6f3c1e-9a7d-4c2b-8e1f-2d3c4b5a6f70")).toBe(true);
  for (const bad of ["", "../threads", "import-0b6f3c1e-9a7d-4c2b-8e1f-2d3c4b5a6f70", "0B6F3C1E-9A7D-4C2B-8E1F-2D3C4B5A6F70x"]) {
    expect(isAskThreadId(bad), bad).toBe(false);
  }
});

test("Registry filters round-trip, and defaults stay out of the address", () => {
  const picked: Filters = { ...DEFAULTS, kind: "funder", theme: "Health", where: "ne", q: "tata" };
  const href = withParams("http://x/registry", filterParams(picked));
  expect(Object.fromEntries(params(href))).toEqual({ type: "funder", theme: "Health", where: "ne", q: "tata" });
  expect(filtersFrom(params(href))).toEqual(picked);
  expect(withParams(href, filterParams({ ...DEFAULTS, kind: "all" }))).toBe("http://x/registry");
});

test("the old /orgs and /funders bucket links still pick the bucket", () => {
  expect(filtersFrom(params("/registry?type=cso")).kind).toBe("org");
  expect(filtersFrom(params("/registry?type=funder")).kind).toBe("funder");
  expect(filtersFrom(params("/registry?type=bogus")).kind).toBe("all");
});
