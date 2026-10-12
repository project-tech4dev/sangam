import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Breadcrumbs, Tag } from "@/components/ui";
import { SectionIndex } from "@/components/ui/SectionIndex";
import type { Brief, Finding } from "./parseBrief";

const STATUS_TONE: Record<string, "accent" | "accent-2" | "neutral"> = { complete: "accent-2", partial: "accent" };
const CONFIDENCE_TONE: Record<string, "accent-2" | "neutral" | "outline"> = { high: "accent-2", medium: "neutral", low: "outline" };

function External({ href, children }: { href?: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

// A funder brief's summary ends in "TEN FIELDS: (1) … (10) …", the intake skill's ten answers: show them as a list.
function splitSummary(summary: string): { intro: string; fields: string[] } {
  const at = summary.search(/TEN FIELDS:/i);
  if (at < 0) return { intro: summary, fields: [] };
  const fields = summary
    .slice(at)
    .replace(/^TEN FIELDS:\s*/i, "")
    .split(/\s*\(\d{1,2}\)\s+/)
    .map((f) => f.trim())
    .filter(Boolean);
  return fields.length > 1 ? { intro: summary.slice(0, at).trim(), fields } : { intro: summary, fields: [] };
}

function FindingRow({ finding }: { finding: Finding }) {
  const { headlines, year, basis, evidence, source } = finding;
  return (
    <li className="brief-finding">
      <div className="brief-finding-head">
        {headlines.map((h) => (
          <strong key={h}>{h}</strong>
        ))}
        {(year || basis) && (
          <span className="brief-finding-when">
            {year}
            {year && basis && " · "}
            {basis && <em>{basis}</em>}
          </span>
        )}
      </div>
      {evidence && <blockquote className="brief-quote">{evidence}</blockquote>}
      {source && (
        <div className="brief-source">
          {source.url ? <External href={source.url}>{source.name}</External> : <span>{source.name}</span>}
          <Tag tone={CONFIDENCE_TONE[source.confidence] ?? "outline"}>confidence {source.confidence}</Tag>
        </div>
      )}
    </li>
  );
}

/** A funder's research brief as a page: the summary, then each finding with the sentence and source behind it. */
export function BriefArticle({ brief, slug, rawUrl }: { brief: Brief; slug: string; rawUrl: string }) {
  const summary = splitSummary(brief.summary);
  const index = [{ id: "summary", label: "Summary" }, ...brief.sections.map((s) => ({ id: s.id, label: s.title }))];
  if (brief.notFound || brief.sources.length) index.push({ id: "gaps", label: "Gaps and sources" });

  return (
    <div className="page reading brief">
      <Breadcrumbs
        items={[
          { label: "Registry", href: "/registry" },
          { label: "Funders", href: "/registry?type=funder" },
          { label: brief.name, href: `/registry/funders/${slug}` },
          { label: "Research brief" },
        ]}
      />
      <header className="brief-head">
        <div className="eyebrow">Research brief</div>
        <h1>{brief.name}</h1>
        <div className="brief-meta">
          {brief.researched && <span>Researched {brief.researched}</span>}
          {brief.status && <Tag tone={STATUS_TONE[brief.status] ?? "neutral"}>{brief.status}</Tag>}
          {brief.website && <External href={brief.website}>{brief.website.replace(/^https?:\/\/(www\.)?/, "")}</External>}
        </div>
      </header>

      <div className="brief-layout">
        <SectionIndex sections={index} title="In this brief" />
        <article className="brief-body">
          <section id="summary" className="brief-section">
            {brief.stopped && (
              <div className="card brief-note">
                <div className="card-kicker">Why it stopped</div>
                <div className="card-body">{brief.stopped}</div>
              </div>
            )}
            {summary.intro && <p className="measure">{summary.intro}</p>}
            {summary.fields.length > 0 && (
              <ol className="brief-fields measure">
                {summary.fields.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ol>
            )}
            {brief.goals.length > 0 && (
              <details className="brief-goals">
                <summary>What it set out to find ({brief.goals.length})</summary>
                <ul>
                  {brief.goals.map((g) => (
                    <li key={g}>{g}</li>
                  ))}
                </ul>
              </details>
            )}
          </section>

          {brief.sections.map((s) => (
            <section key={s.id} id={s.id} className="brief-section">
              <h2>{s.title}</h2>
              {s.findings.length > 0 && (
                <ul className="brief-findings">
                  {s.findings.map((f, i) => (
                    <FindingRow key={i} finding={f} />
                  ))}
                </ul>
              )}
              {s.text && (
                // Text from pages on the open web: never raw HTML, never a javascript: link.
                <div className="answer-md">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    skipHtml
                    urlTransform={defaultUrlTransform}
                    components={{ a: ({ href, children }) => <External href={href}>{children}</External> }}
                  >
                    {s.text}
                  </ReactMarkdown>
                </div>
              )}
            </section>
          ))}

          {(brief.notFound || brief.sources.length > 0) && (
            <section id="gaps" className="brief-section">
              <h2>Gaps and sources</h2>
              {brief.notFound && (
                <p className="measure">
                  <strong>Looked for, not found:</strong> {brief.notFound}
                </p>
              )}
              {brief.sources.length > 0 && (
                <ul className="brief-sources">
                  {brief.sources.map((u) => (
                    <li key={u}>
                      <External href={u}>{u}</External>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          <footer className="brief-foot">
            <p className="muted">
              Findings, not catalog rows. A fact here is something a source said, with the sentence that says it;
              putting it in the catalog is a separate step.
            </p>
            <a href={`${rawUrl}&download=${slug}.md`} className="btn btn-secondary">
              Download .md
            </a>
          </footer>
        </article>
      </div>
    </div>
  );
}
