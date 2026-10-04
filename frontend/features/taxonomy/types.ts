// Shapes of the taxonomy seed files (features-plans/data-model/seed/data/taxonomy).

export type CsrRef = { clause: string; sector: string };

export type SubTheme = {
  code: string;
  label: string;
  /** SDG goal numbers this sub-theme reports against. */
  sdgs: string[];
  /** Schedule VII clause and MCA sector: what a CSR filing for this work is filed under. */
  csr: CsrRef[];
  schemes: string[];
};

export type Theme = { code: string; label: string; sub_themes: SubTheme[] };

export type Domain = {
  domain: string;
  label: string;
  status: "draft" | "active";
  source: string;
  themes: Theme[];
};

export type Lens = { code: string; label: string; adds_sdgs: string[] };

export type Themes = { version: string; lenses: Lens[]; domains: Domain[] };

export type Common = {
  sdgs: [string, string][];
  population: [string, string][];
};
