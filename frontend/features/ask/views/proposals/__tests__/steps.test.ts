import { expect, it } from "vitest";
import { ANSWERS, STEPS } from "@/features/ask/views/proposals/steps";

it("names five steps and the three gate answers the server accepts", () => {
  expect(STEPS).toHaveLength(5);
  expect(ANSWERS.map(([value]) => value)).toEqual(["yes", "will_have", "no"]);
});
