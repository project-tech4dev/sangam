import type { TraceStep } from "@/lib/useAgentChat";

/*
 * The signed-out preview's sample answer. It is static, so showing it costs no model
 * call, but it is not invented: every figure comes from the base's fit-score rows for
 * KABIL × Axis Bank Foundation (rubric v1, fit_scores / fit_score_items /
 * score_adjustments), and the trace lists the tools the agent uses for this question.
 *
 * Citation ids are local to this file and resolve through `index` to slugs, so the
 * chips link correctly whichever database the preview runs against.
 */

export const SAMPLE_QUESTION = "How well does KABIL fit Axis Bank Foundation, and why?";

export const SAMPLE_INDEX = {
  orgs: [[1, { slug: "kabil", name: "KABIL" }]],
  funders: [[1, { slug: "axis-bank-foundation", name: "Axis Bank Foundation" }]],
  scores: [[1, { funderSlug: "axis-bank-foundation", orgName: "KABIL", funderName: "Axis Bank Foundation" }]],
  activities: [],
} as const;

export const SAMPLE_TRACE: TraceStep[] = [
  { id: "s1", tool: "db_list_tables", args: {}, result: "", running: false },
  {
    id: "s2",
    tool: "db_describe_table",
    args: { tables: "fit_scores, fit_score_items, rubric_criteria, score_adjustments" },
    result: "",
    running: false,
  },
  {
    id: "s3",
    tool: "db_query",
    args: { purpose: "Find KABIL's latest fit score with Axis Bank Foundation" },
    result: "",
    running: false,
  },
  {
    id: "s4",
    tool: "db_query",
    args: { purpose: "Read the score per criterion, with any vetting adjustments" },
    result: "",
    running: false,
  },
];

export const SAMPLE_ANSWER = `[org:1] is a strong fit for [funder:1]: **93 out of 100** on rubric v1 [score:1].

It scores full marks on sector, geography, target population, grant shape and funder trend. Axis Bank Foundation's Sustainable Livelihoods Programme — natural resources, agriculture, livestock, SHG collectivisation — is a near-exact match to KABIL's core work, and the two already ran a named four-year project in Udalguri, Assam.

Two criteria lost points:

- **Eligibility & compliance, 16 of 20.** 12A, 80G and FCRA are confirmed, but KABIL's CSR-1 registration is not on record, and Axis Bank Foundation spends Section 135 CSR money, where CSR-1 is a legal requirement.
- **Relationship, 7 of 10.** Lowered from 10 in vetting: the project that began in April 2018 ended around March 2022, so the partnership has lapsed rather than being live. The renewal case is strong — it reached 24,765 families against a target of 15,000.

The v1 score was vetted on 10 Sept 2026 by a single rater; the v2 re-score has not been vetted yet.`;

export const SAMPLE_CRITERIA: { label: string; score: number; max: number; why: string }[] = [
  {
    label: "Thematic / sector alignment",
    score: 25,
    max: 25,
    why: "The Sustainable Livelihoods Programme is a near-exact match to KABIL's core work.",
  },
  {
    label: "Eligibility & compliance",
    score: 16,
    max: 20,
    why: "12A, 80G and FCRA confirmed; CSR-1 not on record, which a Section 135 funder requires.",
  },
  { label: "Geography", score: 15, max: 15, why: "A confirmed, named four-year project in Udalguri, Assam." },
  {
    label: "Target population",
    score: 15,
    max: 15,
    why: "Rural poor households, women, SHGs and tribal communities match the stated target.",
  },
  {
    label: "Relationship / warmth",
    score: 7,
    max: 10,
    why: "Lowered from 10 in vetting: the 2018–22 project has concluded, so the link is recent but not live.",
  },
  {
    label: "Funding size & type",
    score: 10,
    max: 10,
    why: "The earlier grant was multi-year and project-based, matching KABIL's scale and design.",
  },
  {
    label: "Funder capacity & trend",
    score: 5,
    max: 5,
    why: "CSR spend grew about 4.7× in four years: ₹91 cr in FY20-21 to ₹427 cr in FY24-25.",
  },
];

export const SAMPLE_FOLLOW_UPS = [
  "What would KABIL need to close the CSR-1 gap?",
  "Which other funders fit KABIL well?",
  "What grants has KABIL received?",
];

export const EXAMPLE_QUESTIONS = [
  SAMPLE_QUESTION,
  "Which organisations in the base work in Assam?",
  "Which funders back livelihoods work?",
  "What grants has KABIL received?",
];
