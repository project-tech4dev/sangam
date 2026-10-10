/* The Proposal Writing Rubric v2, as data: what each section asks, what a strong answer holds, what reads as weak. */

export type Section = { code: string; label: string; question: string; group: Group; strong: string[]; weak: string };
export type Group = "case" | "people" | "money" | "funder";

export const RUBRIC_VERSION = "proposal-v2";
export const MUST_SCORE_2 = ["A6", "A15", "F1"];

const s = (code: string, label: string, question: string, group: Group, strong: string[], weak: string): Section => ({
  code, label, question, group, strong, weak,
});

export const CORE: Section[] = [
  s("A1", "Summary", "Can I repeat this project in two sentences?", "case",
    ["The problem", "The site and community", "The objective", "Two or three results with numbers", "The amount and the duration"],
    "Mission statement or activity list with no numbers or place"),
  s("A2", "Context and target area", "Do I know exactly where this happens and who lives there?", "case",
    ["State, district, block and villages", "Population and livelihoods", "Existing community institutions", "A source for each fact"],
    "General description of the state or region"),
  s("A3", "Problem and baseline", "Is the problem real, local and measured?", "case",
    ["The specific problem at the site", "Current figures with source and year", "The causes the project will act on"],
    "Broad claims about poverty or climate with no local data"),
  s("A4", "Objectives and results", "What will be different at the end, and by how much?", "case",
    ["Objectives stated as changes", "Results as numbers with units", "Each result linked to an objective"],
    "Objectives written as activities; results with no numbers"),
  s("A5", "Activities and workplan", "Can this team deliver this sequence in this time?", "case",
    ["Activities grouped under results", "An owner, target and timing for each", "Reviews and reports scheduled"],
    "Activities listed with no timing, owner or target"),
  s("A6", "Indicators and M&E", "How will we know it worked?", "case",
    ["Indicators for each result", "Baseline, target, source and frequency", "A named owner", "Mid-term and final reviews"],
    "Indicators that only count activities"),
  s("A7", "Learning and knowledge sharing", "What will others learn from this?", "case",
    ["Named knowledge products", "Who each is for", "How each will be shared"], "One line promising a report"),
  s("A8", "Community participation", "Did the community shape this, and will they steer it?", "people",
    ["Consultations held, with dates and numbers", "Community roles in delivery and monitoring", "Minutes or resolutions attached"],
    "A statement that the community will be involved"),
  s("A9", "Inclusion", "Who could be left out, and what stops that?", "people",
    ["Targets for women, youth, persons with disabilities as relevant", "Their roles in decisions", "Budget lines that pay for it"],
    "Women counted only as attendees; nothing in the budget"),
  s("A10", "Team and organisational capacity", "Who exactly does the work?", "people",
    ["Named staff with role, qualifications and years", "Structure, governance and finance systems"],
    "Team described as experienced professionals with no names"),
  s("A11", "Track record", "Has this organisation done this before, and what changed?", "people",
    ["Comparable past projects", "Funder, amount, place and duration", "Results in numbers"],
    "Project names or partner logos with no results"),
  s("A12", "Partnerships", "Who else is involved, and doing what?", "people",
    ["Each partner named with its role", "A letter or MoU for each"], "A list of names with no roles"),
  s("A13", "Risks and mitigation", "What could stop this working?", "money",
    ["Internal and external risks specific to this project", "A concrete mitigation for each"],
    "Generic risks answered with 'we will monitor'"),
  s("A14", "Sustainability and exit", "What happens the day the grant ends?", "money",
    ["Who runs the work after", "How it is paid for", "Handover steps before, during and at the end"],
    "A statement that community institutions will sustain it"),
  s("A15", "Budget", "Does every rupee trace to an activity?", "money",
    ["Every line tied to an activity", "Unit costs shown", "Totals consistent across sections", "Within the funder's ceiling"],
    "Lump sums; totals that differ"),
  s("A16", "Other funding", "Who else is paying, and is it real?", "money",
    ["Each source with its amount", "Cash or in-kind, committed or projected", "Proof attached"],
    "Other funding claimed with no source or status"),
];

const F1 = s("F1", "Fit with funder priorities", "Does this serve what this funder is trying to do?", "funder",
  ["Names the funder's programme or theme", "Explains the link", "Names related schemes it builds on"],
  "Claims to fit every priority");
// Only when the org has a past partner line with this funder.
const F4 = s("F4", "Earlier phase results", "What did the last phase achieve, and what was learned?", "funder",
  ["Outputs, outcomes and impact of the earlier phase", "Its financial assessment", "Lessons applied now"],
  "Claims of success with no assessment");

export const GROUPS: [Group, string][] = [
  ["case", "The case and the plan"],
  ["people", "People"],
  ["money", "Durability and money"],
  ["funder", "This funder"],
];

export const GATES = { G1: "Eligibility", G2: "Documents" } as const;
export type GateKey = keyof typeof GATES;

export const STEPS = ["Gates", "Template, documents and style", "Sections"] as const;

export const defaultStyle = (org: string) =>
  `Plain, specific English for a CSR programme officer who reads many proposals. Short sentences, active voice, third person ("${org} will…"). Open each section with its strongest fact or number. Name places, groups and dates; no jargon, slogans or superlatives. Money in ₹ with lakh and crore; every figure with its source and year.`;

export const sectionsFor = (earlierPhase: boolean): Section[] => [...CORE, F1, ...(earlierPhase ? [F4] : [])];

/** Display codes: A1–A7 stay, A8–A12 show as B1–B5, A13–A16 as C1–C4, the funder's sections as F1, F2… */
export function displayCodes(sections: Section[]): Record<string, string> {
  const out: Record<string, string> = {};
  let f = 0;
  for (const { code } of sections) {
    const n = Number(code.slice(1));
    out[code] = code.startsWith("A") ? (n <= 7 ? code : n <= 12 ? `B${n - 7}` : `C${n - 12}`) : `F${++f}`;
  }
  return out;
}
