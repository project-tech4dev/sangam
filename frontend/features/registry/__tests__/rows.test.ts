import { describe, expect, it } from "vitest";
import type { RegistryRow } from "@/lib/api";
import { kindLine, signal } from "@/features/registry/rows";

const row = (over: Partial<RegistryRow> = {}): RegistryRow => ({
  kind: "org", id: 1, slug: "kabil", name: "KABIL Trust", funder_type: null, place: null, states: [],
  themes: [], populations: [], sdgs: [], csr1: false, has_12a_80g: false, fcra: false, intake_mode: null,
  open_call: false, partners: 0, csr_prescribed: null, csr_year: null, press: 0, social: 0, posts_since: null,
  research_runs: 0, researched_on: null, ...over,
});

describe("kindLine", () => {
  it("names a CSO's place and how many more states it reaches", () => {
    expect(kindLine(row())).toBe("CSO");
    expect(kindLine(row({ place: "Assam", states: ["Assam"] }))).toBe("CSO · Assam");
    expect(kindLine(row({ place: "Assam", states: ["Assam", "Bihar"] }))).toBe("CSO · Assam and 1 more state");
    expect(kindLine(row({ place: "Assam", states: ["Assam", "Bihar", "Goa"] }))).toBe("CSO · Assam and 2 more states");
  });

  it("lists up to three funder states, then counts them and names a north-east one", () => {
    const f = { kind: "funder" as const, funder_type: "corporate_csr" };
    expect(kindLine(row(f))).toBe("Corporate CSR");
    expect(kindLine(row({ ...f, states: ["Goa", "Bihar"] }))).toBe("Corporate CSR · Goa, Bihar");
    expect(kindLine(row({ ...f, states: ["Goa", "Bihar", "Kerala", "Sikkim"] }))).toBe(
      "Corporate CSR · 4 states, including Sikkim",
    );
    expect(kindLine(row({ ...f, states: ["Goa", "Bihar", "Kerala", "Punjab"] }))).toBe("Corporate CSR · 4 states");
  });
});

describe("signal", () => {
  it("says a row with nothing known has not been researched", () => {
    expect(signal(row())).toBe("Not researched yet");
  });

  it("joins a funder's money, call, intake and partners", () => {
    const line = signal(row({
      kind: "funder", csr_prescribed: 42_000_000, csr_year: "FY2024", open_call: true,
      intake_mode: "invitation_only", partners: 1, research_runs: 1, researched_on: "2026-10-12",
    }));
    expect(line).toBe("₹4.2 crore prescribed CSR, FY2024 · open call now · invites partners · 1 partner · researched 12 Oct");
  });

  it("counts an org's funders, posts and stories in the right number", () => {
    expect(signal(row({ partners: 2, social: 3, posts_since: "2026-04-01", press: 1, research_runs: 1 }))).toBe(
      "2 funders named · 3 posts since April · 1 public story · researched",
    );
    expect(signal(row({ partners: 1, social: 1, press: 2 }))).toBe(
      "1 funder named · 1 post · 2 public stories · Not researched yet",
    );
  });

  it("flags a researched org with no stories", () => {
    expect(signal(row({ research_runs: 2 }))).toBe("Researched · no stories yet");
    expect(signal(row({ kind: "funder", partners: 3, research_runs: 1 }))).toBe("3 partners · researched");
  });
});
