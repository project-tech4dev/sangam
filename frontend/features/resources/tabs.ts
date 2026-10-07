import type { IndexEntry } from "@/components/ui/SectionIndex";
import { DOMAINS } from "@/features/taxonomy/data";

// Resources is one page with a tab per subject; each tab is its own URL (/resources/<id>)
// and lists its sections in the "In this article" index.

export const METHODOLOGY_SECTIONS: IndexEntry[] = [
  { id: "the-base", label: "What the base is" },
  { id: "sources", label: "Where the data comes from" },
  { id: "pipeline", label: "From source to Registry" },
  { id: "answers", label: "How an answer is made" },
  { id: "fit-scores", label: "How a fit score is made" },
  { id: "confidence", label: "What confidence means" },
  { id: "limits", label: "Known limits" },
];

export const TAXONOMY_SECTIONS: IndexEntry[] = [
  { id: "how-it-works", label: "How the taxonomy works" },
  ...DOMAINS.map((d) => ({ id: d.domain, label: d.label })),
  { id: "shared-vocabulary", label: "Shared vocabulary" },
];

export const TABS = [
  { id: "methodology", label: "Methodology", blurb: "How the base is built, and how an answer and a fit score are made.", sections: METHODOLOGY_SECTIONS },
  { id: "taxonomy", label: "Taxonomy", blurb: "How programmes are classified, domain by domain.", sections: TAXONOMY_SECTIONS },
] as const;

export type TabId = (typeof TABS)[number]["id"];

export const isTabId = (id: string): id is TabId => TABS.some((t) => t.id === id);
