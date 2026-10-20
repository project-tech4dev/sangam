import { describe, expect, it } from "vitest";
import { safeNextPath } from "@/lib/safe-next-path";

const origin = "https://sangam.example";

describe("safeNextPath", () => {
  it("keeps a same-origin path with its query and hash", () => {
    expect(safeNextPath("/ask?view=import#top", "/", origin)).toBe("/ask?view=import#top");
  });
  it("refuses anything that would leave the site", () => {
    expect(safeNextPath("//evil.example/x", "/", origin)).toBe("/");
    expect(safeNextPath("https://evil.example", "/", origin)).toBe("/");
    expect(safeNextPath(undefined, "/home", origin)).toBe("/home");
  });
});
