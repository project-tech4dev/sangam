import type { Proposal, Work } from "@/features/ask/views/proposals/api";

// One proposal to Axis from KABIL; a test overrides only the work it is about.
export function proposal(work: Partial<Work> = {}, over: Partial<Proposal> = {}): Proposal {
  return {
    id: 3,
    title: "Axis proposal",
    org: { id: 1, slug: "kabil", name: "KABIL" },
    funder: { id: 10, slug: "axis", name: "Axis" },
    fit_score: 80,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-02T00:00:00Z",
    summary: { stage: work.stage ?? 1, gates_answered: 0, gates_total: 1, done: 1, total: 3, fix_first: [], worth_checking: [], ready: false },
    can_edit: true,
    thread_id: "proposal-3-u1",
    work: {
      stage: 1,
      requirements: [{ key: "csr1", label: "CSR-1 registration", rule: "Must hold CSR-1", on_record: "CSR-1 on file", hard: true }],
      gates: {},
      earlier_phase: false,
      template: null,
      skipped_template: false,
      sources: [],
      style: "Plain and short",
      sections: {},
      facts: {},
      ...work,
    },
    sections: [
      { code: "A1", label: "Problem", question: "What problem?", tab: "need", strong: ["data", "place"], weak: "vague", must_score_2: true, last: false },
      { code: "A2", label: "Place", question: "Where?", tab: "need", strong: [], weak: "thin", must_score_2: false, last: false },
      { code: "B1", label: "Budget", question: "How much?", tab: "money", strong: [], weak: "none", must_score_2: false, last: true },
    ],
    tabs: [
      { key: "need", label: "Need" },
      { key: "money", label: "Money" },
      { key: "unused", label: "Unused" },
    ],
    ...over,
  };
}
