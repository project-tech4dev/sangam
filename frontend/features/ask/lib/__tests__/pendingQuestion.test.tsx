import { afterEach, expect, it, vi } from "vitest";
import { savePendingQuestion, takePendingQuestion } from "@/features/ask/lib/pendingQuestion";

afterEach(() => vi.restoreAllMocks());

it("returns the saved question once, trimmed", () => {
  savePendingQuestion("  Who funds Assam?  ");
  expect(takePendingQuestion()).toBe("Who funds Assam?");
  expect(takePendingQuestion()).toBeNull();
});

it("treats a blank question as none", () => {
  savePendingQuestion("   ");
  expect(takePendingQuestion()).toBeNull();
});

it("survives storage that throws", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
  expect(() => savePendingQuestion("q")).not.toThrow();
  expect(takePendingQuestion()).toBeNull();
});
