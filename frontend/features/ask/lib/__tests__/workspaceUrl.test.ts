import { expect, it } from "vitest";
import { viewParams } from "@/features/ask/lib/workspaceUrl";
import { COMING_SOON } from "@/features/ask/lib/comingSoon";

it("a non-chat view names itself and clears other screens' ids", () => {
  expect(viewParams("vault")).toEqual({ view: "vault", proposal: null, funder: null, org: null });
  expect(viewParams("ask").view).toBeNull();
});

it("nothing is held back as coming soon", () => {
  expect(COMING_SOON.size).toBe(0);
});
