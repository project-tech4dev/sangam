import { describe, expect, it } from "vitest";
import { pickIdentifier, statusLabel, statusTone } from "@/features/registry/identifierStatus";

type Id = { id_type: string; status: string; is_current: boolean; source_type: string | null; evidence: string | null; id_value: string | null };
const id = (over: Partial<Id>): Id => ({
  id_type: "fcra", status: "registered", is_current: true, source_type: "registry", evidence: null, id_value: "123", ...over,
});

describe("pickIdentifier", () => {
  it("returns nothing when the type is absent", () => {
    expect(pickIdentifier([id({ id_type: "pan" })], "fcra")).toBeUndefined();
  });

  it("prefers the current row over a stronger stale one", () => {
    const stale = id({ is_current: false, source_type: "registry" });
    const current = id({ is_current: true, source_type: "seed" });
    expect(pickIdentifier([stale, current], "fcra")).toBe(current);
  });

  it("lets the org's own document outrank an aggregator", () => {
    const agg = id({ status: "registered", source_type: "aggregator" });
    const own = id({ status: "applied", source_type: "org_document" });
    expect(pickIdentifier([agg, own], "fcra")).toBe(own);
  });

  it("ranks a person's entry with the registry, then a numbered row first", () => {
    const manual = id({ source_type: null, id_value: null });
    const funder = id({ source_type: "funder" });
    expect(pickIdentifier([funder, manual], "fcra")).toBe(manual);
    const numbered = id({ source_type: "registry", id_value: "9" });
    const blank = id({ source_type: "registry", id_value: null });
    expect(pickIdentifier([blank, numbered], "fcra")).toBe(numbered);
    expect(pickIdentifier([id({ source_type: "unknown_kind" }), id({ source_type: "seed" })], "fcra")?.source_type).toBe("seed");
  });
});

describe("statusLabel and statusTone", () => {
  it("says when nothing was entered", () => {
    expect(statusLabel(undefined)).toBe("Not entered");
    expect(statusTone(undefined)).toBe("none");
  });

  it("labels known and unknown statuses and marks a claim", () => {
    expect(statusLabel(id({ status: "check_blocked" }))).toBe("Check blocked");
    expect(statusLabel(id({ status: "applied", evidence: "claimed" }))).toBe("Applied (claimed)");
    expect(statusLabel(id({ status: "odd_state" }))).toBe("odd_state");
  });

  it("never reads a blocked check as valid", () => {
    expect(statusTone(id({ status: "registered" }))).toBe("good");
    expect(statusTone(id({ status: "provisional" }))).toBe("good");
    expect(statusTone(id({ status: "check_blocked" }))).toBe("pending");
    expect(statusTone(id({ status: "applied" }))).toBe("pending");
    expect(statusTone(id({ status: "expired" }))).toBe("bad");
  });
});
