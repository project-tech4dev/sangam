import { describe, expect, it } from "vitest";
import { parseBrief, stripComments } from "@/features/registry/brief/parseBrief";

describe("stripComments", () => {
  it.each([
    ["<!-- note -->kept", "kept"],
    ["<!<!-- x -->-- y -->kept", "kept"],
    ["<!-<!-- a -->- b -->kept", "kept"],
    ["kept<!<!---->", "kept<!"],
    ["kept<!-- never closed", "kept never closed"],
  ])("leaves no <!-- in %j", (input, out) => {
    expect(stripComments(input)).toBe(out);
    expect(stripComments(input)).not.toContain("<!--");
  });

  it("strips a long run of unclosed markers quickly", () => {
    const started = Date.now();
    expect(stripComments("<!--".repeat(50_000) + "kept")).toBe("kept");
    expect(Date.now() - started).toBeLessThan(1000);
  });

  it("leaves text with no comment as it is", () => {
    expect(stripComments("a -> b, <! c")).toBe("a -> b, <! c");
  });
});

describe("parseBrief", () => {
  it("reads the name past a comment that rejoins after one pass", () => {
    expect(parseBrief("<!<!-- x -->-- y -->\n# Tata Trusts\n").name).toBe("Tata Trusts");
  });
});
