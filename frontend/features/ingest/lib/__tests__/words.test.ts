import { describe, expect, it } from "vitest";
import { kindLabel, pageOutcome, plainReason, profileHref, researchState } from "../words";
import type { ResearchRecord } from "../types";

const record = (over: Partial<ResearchRecord> = {}): ResearchRecord => ({
  id: 1, entity_name: "KABIL", canonical_name: null, entity_kind: "org", slug: "kabil", status: "complete",
  stopped_reason: null, summary: "", fact_count: 0, sources_read: [], not_found: [], researched_at: "2026-10-01",
  saved_at: null, resolved_org_id: null, resolved_funder_id: null, ...over,
});

describe("kindLabel", () => {
  it("names funders and NGOs, and anything else as an organisation", () => {
    expect(kindLabel("funder")).toBe("Funder");
    expect(kindLabel("org")).toBe("NGO");
    expect(kindLabel("cso")).toBe("Organisation");
  });
});

describe("researchState", () => {
  it("reads each outcome in staff words", () => {
    expect(researchState(record({ status: "not_found" })).label).toBe("Couldn't find it");
    expect(researchState(record({ status: "wrong_entity" })).label).toBe("Found a different organisation");
    expect(researchState(record({ resolved_org_id: 3 }))).toEqual({ label: "Saved", tag: "tag-accent-2" });
    expect(researchState(record({ saved_at: "2026-10-02" })).label).toBe("Saved");
    expect(researchState(record())).toEqual({ label: "Not saved", tag: "tag-neutral" });
  });
});

describe("profileHref", () => {
  it("links a funder or an org profile, or nothing", () => {
    expect(profileHref(record({ resolved_funder_id: 5 }))).toBe("/registry/funders/5");
    expect(profileHref(record({ resolved_org_id: 9 }))).toBe("/registry/9");
    expect(profileHref(record())).toBeNull();
  });
});

describe("pageOutcome", () => {
  it("is opening while running and blocked once stopped with nothing", () => {
    expect(pageOutcome(null, true)).toEqual({ state: "opening", text: "Opening…" });
    expect(pageOutcome(null, false)).toEqual({ state: "blocked", text: "Couldn't open" });
  });

  it("recognises a scan, a read and a failure", () => {
    expect(pageOutcome("This PDF is most likely scanned", false).state).toBe("scanned");
    expect(pageOutcome("Lots of text", false)).toEqual({ state: "read", text: "Read" });
    expect(pageOutcome("ERROR: Client error '403 Forbidden' for url 'x'", false).text).toBe("Couldn't open — the site said no");
    expect(pageOutcome("ERROR: connection reset", false).text).toBe("Couldn't open");
  });
});

describe("plainReason", () => {
  it("puts status codes into words", () => {
    expect(plainReason("HTTP 429 Too Many Requests")).toBe("the site said no");
    expect(plainReason("HTTP 410 Gone")).toBe("the page isn't there");
    expect(plainReason("HTTP 502 Bad Gateway")).toBe("the site had a problem");
    expect(plainReason("HTTP 418 I'm a teapot")).toBe("I'm a teapot");
    expect(plainReason("HTTP 418")).toBe("it didn't work");
  });
});
