// Back returns to the previous screen only because each screen round-trips through its URL; these pin that.
import { test } from "node:test";
import assert from "node:assert/strict";
import { idParam, oneOf, withParams } from "../lib/url.ts";
import { isAskThreadId, viewFrom, viewParams, WORKSPACE_VIEWS } from "../features/ask/lib/workspaceUrl.ts";
import { DEFAULTS, filterParams, filtersFrom, type Filters } from "../features/registry/filtersUrl.ts";

const params = (href: string) => new URL(href, "http://x").searchParams;

test("withParams sets, replaces and drops params, leaving the rest", () => {
  const href = "http://x/ask?view=proposals&proposal=4&thread=t";
  assert.equal(withParams(href, { proposal: null }), "http://x/ask?view=proposals&thread=t");
  assert.equal(withParams(href, { proposal: "9" }), "http://x/ask?view=proposals&proposal=9&thread=t");
  assert.equal(withParams(href, { view: "", proposal: undefined }), "http://x/ask?thread=t");
});

test("idParam accepts only positive integers", () => {
  assert.equal(idParam("12"), 12);
  for (const bad of [null, "", "0", "-3", "1.5", "abc", "12abc"]) assert.equal(idParam(bad), null, String(bad));
});

test("oneOf falls back to the first id", () => {
  const tabs = ["mandate", "giving", "reach"] as const;
  assert.equal(oneOf("giving", tabs), "giving");
  assert.equal(oneOf(null, tabs), "mandate");
  assert.equal(oneOf("nope", tabs), "mandate");
});

test("every workspace view round-trips through the address", () => {
  for (const view of WORKSPACE_VIEWS) {
    const href = withParams("http://x/ask", viewParams(view));
    assert.equal(viewFrom(params(href).get("view")), view);
  }
  assert.equal(viewFrom(null), "ask");
  assert.equal(viewFrom("import"), "ask");
});

test("a sidebar pick clears the last screen's ids but keeps the open chat", () => {
  const href = withParams("http://x/ask?view=proposals&proposal=4&funder=2&org=kabil&thread=t", viewParams("vault"));
  assert.equal(href, "http://x/ask?view=vault&thread=t");
  assert.equal(withParams(href, viewParams("ask")), "http://x/ask?thread=t");
});

test("only a UUID is taken as an Ask thread from the address", () => {
  assert.ok(isAskThreadId("0b6f3c1e-9a7d-4c2b-8e1f-2d3c4b5a6f70"));
  for (const bad of ["", "../threads", "import-0b6f3c1e-9a7d-4c2b-8e1f-2d3c4b5a6f70", "0B6F3C1E-9A7D-4C2B-8E1F-2D3C4B5A6F70x"]) {
    assert.ok(!isAskThreadId(bad), bad);
  }
});

test("Registry filters round-trip, and defaults stay out of the address", () => {
  const picked: Filters = { ...DEFAULTS, kind: "funder", theme: "Health", where: "ne", q: "tata" };
  const href = withParams("http://x/registry", filterParams(picked));
  assert.deepEqual(Object.fromEntries(params(href)), { type: "funder", theme: "Health", where: "ne", q: "tata" });
  assert.deepEqual(filtersFrom(params(href)), picked);
  assert.equal(withParams(href, filterParams({ ...DEFAULTS, kind: "all" })), "http://x/registry");
});

test("the old /orgs and /funders bucket links still pick the bucket", () => {
  assert.equal(filtersFrom(params("/registry?type=cso")).kind, "org");
  assert.equal(filtersFrom(params("/registry?type=funder")).kind, "funder");
  assert.equal(filtersFrom(params("/registry?type=bogus")).kind, "all");
});
