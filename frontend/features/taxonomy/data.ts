import common from "./data/common.json";
import themes from "./data/themes.json";
import type { Common, Domain, Lens, Themes } from "./types";

const THEMES = themes as Themes;

export const DOMAINS: Domain[] = THEMES.domains;
export const LENSES: Lens[] = THEMES.lenses;
export const COMMON = common as unknown as Common;

export const SDG_LABEL = new Map(COMMON.sdgs);

/** Every Schedule VII sector some sub-theme files under, grouped by clause — the CSR crosswalk at a glance. */
export function scheduleViiInUse(): { clause: string; sectors: string[] }[] {
  const byClause = new Map<string, Set<string>>();
  for (const d of DOMAINS)
    for (const t of d.themes)
      for (const s of t.sub_themes)
        for (const { clause, sector } of s.csr) {
          if (!byClause.has(clause)) byClause.set(clause, new Set());
          byClause.get(clause)!.add(sector);
        }
  const order = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"];
  return [...byClause.entries()]
    .sort(([a], [b]) => order.indexOf(a) - order.indexOf(b))
    .map(([clause, sectors]) => ({ clause, sectors: [...sectors].sort() }));
}
