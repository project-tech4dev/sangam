import { describe, expect, it } from "vitest";
import { accessOf, canUseScout, tasksFor, type Me } from "../access";
import { isPull, leadIn } from "../composePrompt";

const staff: Me = { is_staff: true, memberships: [] };
const steward: Me = {
  is_staff: false,
  memberships: [
    { org_slug: "kabil", org_name: "KABIL", role: "steward" },
    { org_slug: "pratham", org_name: "Pratham", role: "member" },
  ],
};
const member: Me = { is_staff: false, memberships: [{ org_slug: "pratham", org_name: "Pratham", role: "member" }] };

describe("accessOf", () => {
  it("lists every org but only the stewarded ones as stewardOf", () => {
    expect(accessOf(steward)).toEqual({
      staff: false,
      stewardOf: ["KABIL"],
      orgs: [{ slug: "kabil", name: "KABIL" }, { slug: "pratham", name: "Pratham" }],
    });
  });
});

describe("canUseScout", () => {
  it("lets staff and stewards in, and nobody else", () => {
    expect(canUseScout(staff)).toBe(true);
    expect(canUseScout(steward)).toBe(true);
    expect(canUseScout(member)).toBe(false);
  });
});

describe("tasksFor", () => {
  it("gives staff every task, a steward research only, a member none", () => {
    expect(tasksFor(accessOf(staff))).toEqual(["funder", "ngo", "news", "calls"]);
    expect(tasksFor(accessOf(steward))).toEqual(["funder", "ngo"]);
    expect(tasksFor(accessOf(member))).toEqual([]);
  });
});

describe("composePrompt", () => {
  it("treats news and calls as fixed pulls", () => {
    expect(isPull("news")).toBe(true);
    expect(isPull("calls")).toBe(true);
    expect(isPull("funder")).toBe(false);
    expect(isPull(null)).toBe(false);
  });

  it("writes the words staff used to type", () => {
    expect(leadIn("news")).toBe("Get the latest news for everyone in Sangam");
    expect(leadIn("calls")).toMatch(/^Check open calls/);
    expect(leadIn("ngo")).toBe("Legal and operational standing of the NGOs ");
    expect(leadIn("funder")).toBe("Funding profile for ");
  });
});
