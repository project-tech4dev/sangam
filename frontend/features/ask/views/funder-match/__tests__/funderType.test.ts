import { expect, it } from "vitest";
import { funderTypeGroup, funderTypeLabel } from "@/features/ask/views/funder-match/funderType";

it("labels the fixed funder types and groups them by the part before the dot", () => {
  expect(funderTypeLabel("corporate_csr")).toBe("Corporate CSR · run by the company");
  expect(funderTypeGroup("csr_foundation")).toBe("Corporate CSR");
  expect(funderTypeGroup("family_trust")).toBe("Private or family foundation");
});

it("calls anything else Other", () => {
  expect(funderTypeLabel(null)).toBe("Other");
  expect(funderTypeLabel("bilateral")).toBe("Other");
  expect(funderTypeGroup(null)).toBe("Other");
});
