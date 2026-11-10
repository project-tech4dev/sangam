// Reads the markdown `backend/app/ingest/brief.py::entity_markdown` writes; keep the two in step.

export type Source = { name: string; url: string; confidence: string };
export type Detail = { label: string; value: string };
export type Finding = {
  headlines: string[];
  year?: string;
  basis?: string;
  evidence: string;
  source?: Source;
  details?: Detail[];
};
export type BriefSection = { id: string; title: string; findings: Finding[]; text?: string };
export type Brief = {
  name: string;
  researched?: string;
  status?: string;
  stopped?: string;
  summary: string;
  website?: string;
  goals: string[];
  sections: BriefSection[];
  notFound?: string;
  sources: string[];
};

const GOALS = "What it set out to find";
const NOT_FOUND = "Looked for, not found";
const SOURCES = "Sources read";

const FINDING = /^- \*\*(.+?)\*\*(?: \(([^)]+)\))?(?: _([^_]+)_)?\s*$/;
const STATUS = /^Researched (\S+) · status \*\*([^*]+)\*\*(?: · (.*))?$/;
const SOURCE = /^\s*<sub>(.*)<\/sub>\s*$/;
const DETAIL = /^  - ([^:]+): (.*)$/; // a programme's description, themes, places, funders, spend and results

function slugify(title: string) {
  return title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function parseSource(inner: string): Source {
  const parts = inner.split(" · ");
  const confidence = (parts.pop() ?? "").replace(/^confidence\s+/, "");
  const url = parts.pop() ?? "";
  return { name: parts.join(" · ") || "source", url, confidence };
}

// One sentence quoted once per row reads as one finding: "Bihar · Creches" and "Odisha · Creches"
// become "Bihar · Odisha — Creches"; rows with no shared tail stay as separate lines under the quote.
function fold(findings: Finding[]): Finding[] {
  const out: Finding[] = [];
  const byKey = new Map<string, Finding>();
  for (const f of findings) {
    const key = `${f.evidence}\u0000${f.source?.url ?? ""}\u0000${f.year ?? ""}`;
    const seen = byKey.get(key);
    if (seen) seen.headlines.push(...f.headlines.filter((h) => !seen.headlines.includes(h)));
    else {
      const copy = { ...f, headlines: [...f.headlines] };
      byKey.set(key, copy);
      out.push(copy);
    }
  }
  for (const f of out) {
    if (f.headlines.length < 2) continue;
    const parts = f.headlines.map((h) => h.split(" · "));
    const tail = parts[0].slice(1).join(" · ");
    if (tail && parts.every((p) => p.length > 1 && p.slice(1).join(" · ") === tail)) {
      f.headlines = [`${parts.map((p) => p[0]).join(" · ")} — ${tail}`];
    }
  }
  return out;
}

export function parseBrief(markdown: string): Brief {
  const brief: Brief = { name: "", summary: "", goals: [], sections: [], sources: [] };
  const summary: string[] = [];
  let section: BriefSection | null = null;
  let special: string | null = null;
  let finding: Finding | null = null;
  let raw: string[] = [];

  const close = () => {
    if (section) {
      section.findings = fold(section.findings);
      if (raw.some((l) => l.trim())) section.text = raw.join("\n").trim();
      if (section.findings.length || section.text) brief.sections.push(section);
    }
    section = null;
    finding = null;
    raw = [];
  };

  for (const line of markdown.replace(/<!--[\s\S]*?-->/g, "").split("\n")) {
    if (line.trim() === "---") break; // the closing note is fixed copy, written by the page instead
    if (line.startsWith("# ") && !brief.name) {
      brief.name = line.slice(2).trim();
      continue;
    }
    if (line.startsWith("## ")) {
      close();
      const title = line.slice(3).trim();
      special = [GOALS, NOT_FOUND, SOURCES].includes(title) ? title : null;
      if (!special) section = { id: slugify(title), title, findings: [] };
      continue;
    }
    if (special === GOALS || special === SOURCES) {
      // A source line is "<url> · <type, pages, document>"; the page links the url.
      if (line.startsWith("- ")) {
        const item = line.slice(2).trim();
        if (special === GOALS) brief.goals.push(item);
        else brief.sources.push(item.split(" · ")[0]);
      }
      continue;
    }
    if (special === NOT_FOUND) {
      if (line.trim()) brief.notFound = [brief.notFound, line.trim()].filter(Boolean).join(" ");
      continue;
    }
    if (!section) {
      const status = line.match(STATUS);
      if (status) [, brief.researched, brief.status, brief.stopped] = status;
      else if (line.startsWith("Website: ")) brief.website = line.slice(9).trim();
      else summary.push(line);
      continue;
    }
    const head = line.match(FINDING);
    if (head) {
      finding = { headlines: [head[1]], year: head[2], basis: head[3], evidence: "" };
      section.findings.push(finding);
      continue;
    }
    const current = finding as Finding | null;
    if (current && line.startsWith("  > ")) {
      current.evidence = [current.evidence, line.slice(4)].filter(Boolean).join(" ");
      continue;
    }
    const source = line.match(SOURCE);
    if (current && source) {
      current.source = parseSource(source[1]);
      continue;
    }
    const detail = line.match(DETAIL);
    if (current && detail) {
      (current.details ??= []).push({ label: detail[1], value: detail[2] });
      continue;
    }
    raw.push(line);
  }
  close();
  brief.summary = summary.join("\n").trim();
  return brief;
}
