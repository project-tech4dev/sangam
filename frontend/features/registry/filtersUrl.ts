/* The Registry's filters as URL params, so Back from a profile returns to the same list. Pure. */

export type Filters = {
  kind: "all" | "org" | "funder"; theme: string; population: string; sdg: string; where: string;
  reg: string; ftype: string; approach: string; q: string;
};

export const PAGE = 25;  // rows a batch, on the server's first render and each scroll

export const DEFAULTS: Omit<Filters, "kind"> = {
  theme: "all", population: "all", sdg: "all", where: "any", reg: "any", ftype: "all", approach: "any", q: "",
};

type Field = keyof typeof DEFAULTS;
const FIELDS = Object.keys(DEFAULTS) as Field[];

/** `?type=cso|funder` is the bucket (the old /orgs and /funders links use it); every other filter keeps its name. */
export function filtersFrom(params: { get(name: string): string | null }): Filters {
  const type = params.get("type");
  const f: Filters = { kind: type === "cso" ? "org" : type === "funder" ? "funder" : "all", ...DEFAULTS };
  for (const key of FIELDS) f[key] = params.get(key) || DEFAULTS[key];
  return f;
}

/** The params a filter change writes; a default value drops its param. */
export function filterParams(patch: Partial<Filters>): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  for (const [key, value] of Object.entries(patch)) {
    if (key === "kind") out.type = value === "org" ? "cso" : value === "funder" ? "funder" : null;
    else out[key] = value === DEFAULTS[key as Field] ? null : (value as string);
  }
  return out;
}

/** The paged API's query for these filters: the same names the address uses, defaults left out. */
export function registryQuery(f: Filters, offset: number, limit: number): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filterParams({ ...f, q: f.q.trim() }))) if (value) params.set(key, value);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return params.toString();
}
