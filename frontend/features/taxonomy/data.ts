import common from "./data/common.json";
import education from "./data/education.json";
import health from "./data/health.json";
import livelihoods from "./data/livelihoods.json";
import type { Common, Domain } from "./types";

export const DOMAINS = [livelihoods, education, health] as unknown as Domain[];
export const COMMON = common as unknown as Common;

export const SDG_LABEL = new Map(COMMON.sdgs);
export const SECTOR_LABEL = new Map(COMMON.sectors);
export const POPULATION_LABEL = new Map(COMMON.population);

/** "enabler_kinds" are snake_case codes; show them as words. */
export const humanize = (code: string) => code.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
