import type { MatchRow, PageOf } from "@/lib/api";
import { call } from "../../lib/rest";
import type { Doc } from "../../lib/vault";
import { getDetail } from "../funder-match/api";
import { RUBRIC_VERSION, defaultStyle } from "./rubric";
import { addProposal, type Proposal, type Work } from "./store";

const CSR_TYPES = new Set(["corporate_csr", "corporate_foundation"]);
const BAR = "The funder's own bar";
const clip = (text: string) => (text.length <= 240 ? text : `${text.slice(0, 239).trimEnd()}…`);

/* A new proposal's gates come from the saved Funder Match detail, so they read what the match judged. */
export async function startProposal(org: { slug: string; name: string }, match: MatchRow, title: string): Promise<string> {
  const [{ detail }, templates] = await Promise.all([
    getDetail(match.id),
    call<PageOf<Doc>>(`/api/documents?funder=${encodeURIComponent(match.funder.slug)}&doc_type=proposal_template&limit=1`).catch(
      () => null,
    ),
  ]);
  const eligibility = detail.criteria.find((c) => c.code === "eligibility");
  const parts = eligibility?.note.split("; ").filter(Boolean) ?? [];
  const cites = eligibility?.cites.join(" ") ?? "";
  const held = (lines: string[]) => (lines.length ? `${lines.join("; ")} ${cites}`.trim() : "Nothing on record.");
  const bars = detail.not_judged.filter((line) => line.startsWith(BAR)).map((line) => clip(line.replace(/^[^:]*:\s*/, "")));
  const csr = CSR_TYPES.has(match.funder.funder_type ?? "");
  const relationship = detail.criteria.find((c) => c.code === "relationship");
  const template = templates?.items[0];
  const now = new Date().toISOString();

  const work: Work = {
    rubric_version: RUBRIC_VERSION,
    step: 1,
    gates: {},
    funder_gates: {
      G1: {
        rule: `${csr ? "12A, 80G and CSR Form 1" : "12A and 80G"}; three years' standing`,
        bars,
        on_record: held(parts.filter((p) => !/audit/i.test(p))),
      },
      G2: {
        rule: `${csr ? "CSR-1 certificate, " : ""}audited accounts for three years, annual report`,
        bars: [],
        on_record: held(parts.filter((p) => /audit/i.test(p))),
      },
    },
    earlier_phase: Boolean(relationship && relationship.points),
    template: template ? { document_id: template.id, url: template.source_url, from: "sangam", read_at: template.fetched_at } : null,
    skipped_template: false,
    docs: [],
    style: defaultStyle(org.name),
    sections: {},
  };
  const proposal: Proposal = {
    id: crypto.randomUUID(),
    title,
    org,
    funder: { id: match.funder.id, slug: match.funder.slug, name: match.funder.name },
    fit_score: match.score,
    created_at: now,
    updated_at: now,
    work,
  };
  addProposal(proposal);
  return proposal.id;
}
