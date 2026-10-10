import { Tag } from "@/components/ui";
import { ArticleSection } from "./ResourcesShell";

const LAYERS = [
  {
    name: "Data",
    body: "The vetted registry: organisations, funders, registrations, grants, scores and documents. Every row carries its source and the date it was fetched.",
  },
  {
    name: "Query",
    body: "An agent that answers only from the data layer, shows the steps it took, and cites every claim back to a row.",
  },
  {
    name: "Match & draft",
    body: "Rubric-based fit scoring and proposal-readiness work, where human vetting remains the baseline the model is measured against.",
  },
];

const SOURCES = [
  { name: "NGO Darpan", body: "The government registry of NGOs: registration, credentials such as 12A, 80G and FCRA, office bearers and working sectors." },
  { name: "Funder filings and publications", body: "CSR reports, annual reports and statutory disclosures, read by Sangam Scout from sources whose terms allow it." },
  { name: "News and signals", body: "News coverage of organisations and funders, collected and held for review before it is shown." },
  { name: "Organisations' own documents", body: "What an organisation uploads to its Doc vault. Private to that organisation unless it chooses otherwise." },
];

const PIPELINE = [
  { step: "01 Ingest", body: "Statutory registries, funder publications and news land as raw documents with full provenance." },
  { step: "02 Vet", body: "A person checks registrations against their sources, corrects errors, and records every adjustment in an audit log. Nothing enters the base unattributed." },
  { step: "03 Tag", body: "Organisations, funders and programmes are tagged against the shared taxonomy — sectors, SDGs, geographies — so matching is mechanical where it can be." },
  { step: "04 Publish", body: "Vetted entries appear in the Registry, and the agent answers only from them, citing each claim." },
];

const ANSWER_STEPS = [
  "Reads the question and works out which organisations, funders or scores it is about.",
  "Checks which tables hold that information, then writes a read-only query against them.",
  "Answers from the rows that come back, putting a citation next to every fact; each one links to its Registry entry.",
  "Says so when the base has no answer, instead of filling the gap from general knowledge.",
];

const CONFIDENCE = [
  { band: "High", tone: "accent-2" as const, body: "The question names entities with full, vetted profiles and the rubric applies cleanly. Expect precise, cited numbers." },
  { band: "Medium", tone: "accent" as const, body: "A real match exists, but parts of the evidence are thin or unverified. The answer says which parts." },
  { band: "Low", tone: "neutral" as const, body: "The question falls outside the base. Sangam says so — no rubric is applied and nothing is invented." },
];

export function MethodologyArticle() {
  return (
    <>
      <ArticleSection id="the-base" title="What the base is">
        <p className="measure m-0">
          Sangam is three layers, each built on the one below. Nothing in a higher layer is allowed
          to state a fact the data layer does not hold.
        </p>
        <div className="grid gap-3.5 md:grid-cols-3">
          {LAYERS.map((layer) => (
            <div key={layer.name} className="card" style={{ gap: 6 }}>
              <div className="card-title">{layer.name}</div>
              <div className="card-body">{layer.body}</div>
            </div>
          ))}
        </div>
      </ArticleSection>

      <ArticleSection id="sources" title="Where the data comes from">
        <p className="measure m-0">
          Every row records its source URL, the source&apos;s name and when it was fetched, so any
          field can be traced back to where it came from.
        </p>
        <dl className="m-0 grid gap-x-6 gap-y-3 md:grid-cols-[max-content_minmax(0,1fr)]">
          {SOURCES.map((s) => (
            <div key={s.name} className="contents">
              <dt className="font-semibold">{s.name}</dt>
              <dd className="muted measure m-0">{s.body}</dd>
            </div>
          ))}
        </dl>
      </ArticleSection>

      <ArticleSection id="pipeline" title="From source to Registry">
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            border: "1px solid var(--color-divider)",
            borderRadius: "var(--radius-surface)",
            overflow: "hidden",
          }}
        >
          {PIPELINE.map((item) => (
            <div key={item.step} style={{ padding: 18, borderRight: "1px solid var(--color-divider)" }}>
              <div className="card-kicker" style={{ marginBottom: 6 }}>{item.step}</div>
              <div className="card-body">{item.body}</div>
            </div>
          ))}
        </div>
      </ArticleSection>

      <ArticleSection id="answers" title="How an answer is made">
        <p className="measure m-0">
          Ask Sangam is an agent that reaches the base only through read-only database tools. For
          each question it:
        </p>
        <ol className="measure m-0 flex flex-col gap-2 pl-6">
          {ANSWER_STEPS.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        <p className="measure muted m-0">
          Every answer shows these steps above it, so you can see which tables were read and why. It
          reads a web page only when you ask it to, and then says where the text came from.
        </p>
      </ArticleSection>

      <ArticleSection id="fit-scores" title="How a fit score is made">
        <p className="measure m-0">
          A versioned rubric — v1 has seven criteria worth 100 points; v2 splits the same criteria
          into weighted sub-criteria — is applied to each organisation and funder pair. Every
          criterion score carries a written justification, and any manual correction is kept as an
          adjustment with its reason, so the audit trail ships with the score.
        </p>
      </ArticleSection>

      <ArticleSection id="confidence" title="What confidence means">
        <div className="grid gap-3.5 md:grid-cols-3">
          {CONFIDENCE.map((item) => (
            <div key={item.band} className="card">
              <Tag tone={item.tone}>{item.band}</Tag>
              <div className="card-body">{item.body}</div>
            </div>
          ))}
        </div>
      </ArticleSection>

      <ArticleSection id="limits" title="Known limits">
        <div className="card" style={{ background: "var(--color-accent-100)", border: "none" }}>
          <div className="card-body measure" style={{ color: "var(--color-accent-900)" }}>
            The base covers a small vetted cohort today, and signal collection is manual by design.
            Fit scores are single-rater assessments, not ground truth — which is why every number
            links back to its criteria, justifications and adjustment history.
          </div>
        </div>
      </ArticleSection>
    </>
  );
}
