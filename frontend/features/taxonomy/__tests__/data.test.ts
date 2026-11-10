import { expect, it } from "vitest";
import { DOMAINS, scheduleViiInUse, SDG_LABEL } from "@/features/taxonomy/data";
import { isTabId, TAXONOMY_SECTIONS } from "@/features/resources/tabs";

it("groups Schedule VII sectors by clause in clause order, each sorted and unique", () => {
  const order = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"];
  const rows = scheduleViiInUse();
  expect(rows.length).toBeGreaterThan(0);
  const idx = rows.map((r) => order.indexOf(r.clause));
  expect(idx).toEqual([...idx].sort((a, b) => a - b));
  for (const r of rows) {
    expect(r.sectors).toEqual([...new Set(r.sectors)].sort());
  }
});

it("labels SDGs and gives the taxonomy tab one section per domain", () => {
  expect(SDG_LABEL.size).toBeGreaterThan(0);
  expect(TAXONOMY_SECTIONS.map((s) => s.id)).toEqual(["how-it-works", ...DOMAINS.map((d) => d.domain), "shared-vocabulary"]);
  expect(isTabId("taxonomy")).toBe(true);
  expect(isTabId("nope")).toBe(false);
});
