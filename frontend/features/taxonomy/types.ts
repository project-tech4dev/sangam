// Shapes of the taxonomy seed files (features-plans/data-model/seed/data/taxonomy).

export type Source = { id: string; name: string; publisher: string; url: string | null; used_for: string };

export type Leaf = {
  code: string;
  label: string;
  sdgs: string[];
  sectors: string[];
  /** A variant or modifier code → the extra SDGs a programme carrying it adds. */
  adds: Record<string, string[]>;
  note?: string;
  refs: { sdg_targets?: string[]; india_programmes?: string[]; [key: string]: unknown };
};

export type Area = { code: string; label: string; note?: string; children: Leaf[] };

export type Domain = {
  domain: string;
  label: string;
  version: string;
  status: "draft" | "active" | "deprecated";
  tree_name: string;
  source: string;
  levels: string[];
  variants: {
    level: string;
    apply_to_level: string;
    note?: string;
    items: { code: string; label: string; refs?: { note?: string } }[];
  } | null;
  modifiers: { code: string; label: string }[];
  enabler_kinds: string[];
  notes?: string[];
  sources: Source[];
  nodes: Area[];
};

export type Common = {
  sdgs: [string, string][];
  sectors: [string, string][];
  population: [string, string][];
  darpan_map: Record<string, string[]>;
};
