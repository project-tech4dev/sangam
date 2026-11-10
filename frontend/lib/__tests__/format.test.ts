import { describe, expect, it } from "vitest";
import { dayMonth, dayMonthYear, displayName, formatInr, funderTypeLabel, monthYear, titleCase } from "@/lib/format";

describe("titleCase", () => {
  it("softens Darpan's shouting but keeps short words upper case", () => {
    expect(titleCase("PRATHAM EDUCATION FOUNDATION OF INDIA")).toBe("Pratham Education Foundation OF India");
  });
  it("leaves mixed case and empty values alone", () => {
    expect(titleCase("Teach for India")).toBe("Teach for India");
    expect(titleCase(null)).toBe("");
  });
});

describe("formatInr", () => {
  it("speaks in crore, lakh and rupees", () => {
    expect(formatInr(42_000_000)).toBe("₹4.2 crore");
    expect(formatInr(7_500_000)).toBe("₹75 lakh");
    expect(formatInr(40_000)).toBe("₹40,000");
    expect(formatInr(-150_000)).toBe("-₹1.5 lakh");
  });
});

describe("dates read as text", () => {
  it("drops parts the ISO date does not have", () => {
    expect(dayMonthYear("2026-10-12")).toBe("12 Oct 2026");
    expect(dayMonthYear("2026-10")).toBe("Oct 2026");
    expect(dayMonthYear("2026")).toBe("2026");
    expect(dayMonthYear(null)).toBe("");
  });
  it("gives month and year, short or long", () => {
    expect(monthYear("2026-10-12")).toBe("Oct 2026");
    expect(monthYear("2026-10-12", true)).toBe("October 2026");
    expect(monthYear("2026")).toBe("2026");
    expect(monthYear(undefined)).toBeNull();
    expect(dayMonth("2026-10-02")).toBe("2 Oct");
  });
});

describe("names and funder types", () => {
  it("keeps a one-word acronym and title-cases a shouted name", () => {
    expect(displayName("KABIL")).toBe("KABIL");
    expect(displayName("SMILE FOUNDATION")).toBe("Smile Foundation");
  });
  it("labels known and unknown funder types", () => {
    expect(funderTypeLabel("corporate_csr")).toBe("Corporate CSR");
    expect(funderTypeLabel("impact_investor")).toBe("Impact investor");
    expect(funderTypeLabel(null)).toBe("Funder");
  });
});
