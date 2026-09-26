import { Breadcrumbs, Tag } from "@/components/ui";

export const metadata = { title: "Methodology — Sangam" };

const PIPELINE = [
  { step: "01 Ingest", body: "Statutory registries (NGO Darpan, MCA CSR portal), funder publications, and news/social signals land as raw documents with full provenance." },
  { step: "02 Hand-vet", body: "A human verifies registrations against sources, corrects errors, and records every adjustment in an audit log. Nothing enters the base unattributed." },
  { step: "03 Tag", body: "Organisations, funders, and programs are tagged against the shared taxonomy — sectors, SDGs, geographies — so matching is mechanical where it can be." },
  { step: "04 Publish", body: "Vetted entries appear in the Registry; the agent answers only from them, citing each claim." },
];

const CONFIDENCE = [
  { band: "High", body: "The question names entities with full, hand-vetted profiles and the rubric applies cleanly. Expect precise, cited numbers." },
  { band: "Medium", body: "A real match exists, but parts of the evidence are thin or unverified. The answer says which parts." },
  { band: "Low", body: "The question falls outside the base. Sangam says so — no rubric is applied and nothing is invented." },
];

export default function MethodologyPage() {
  return (
    <div className="page" style={{ display: "flex", flexDirection: "column", gap: 22, maxWidth: 900 }}>
      <Breadcrumbs items={[{ label: "Sangam", href: "/registry" }, { label: "Resources", href: "/resources" }, { label: "Methodology" }]} />
      <div>
        <div className="eyebrow">Methodology</div>
        <h1 style={{ fontSize: 28 }}>How the base is built, and how an answer is made</h1>
      </div>

      <section className="card">
        <div className="card-kicker">Three layers</div>
        <div className="card-body">
          <strong>Data</strong> — the hand-vetted registry: organisations, funders, registrations,
          grants, scores, documents; every row carries its source and fetch date.{" "}
          <strong>Query</strong> — an agent that answers only from the data layer, showing its steps
          and citing every claim. <strong>Match &amp; draft</strong> — rubric-based fit scoring and
          proposal-readiness work, where human hand-vetting remains the baseline the model is
          measured against.
        </div>
      </section>

      <section>
        <h2 style={{ fontSize: 20, marginBottom: 12 }}>The ingest pipeline</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 0, border: "1px solid var(--color-divider)", borderRadius: "var(--radius-lg)", overflow: "hidden" }}>
          {PIPELINE.map((item) => (
            <div key={item.step} style={{ padding: 18, borderRight: "1px solid var(--color-divider)" }}>
              <div className="card-kicker" style={{ marginBottom: 6 }}>{item.step}</div>
              <div style={{ fontSize: 12.5 }} className="muted">{item.body}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <div className="card-kicker">How a fit score is made</div>
        <div className="card-body">
          A versioned rubric (v1: 7 criteria, 100 points; v2: the same criteria split into weighted
          sub-criteria) is applied per organisation × funder pair. Every criterion score carries a
          written justification, and any manual correction is kept as an adjustment with its reason
          — the audit trail ships with the score.
        </div>
      </section>

      <section>
        <h2 style={{ fontSize: 20, marginBottom: 12 }}>What confidence means</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 14 }}>
          {CONFIDENCE.map((item) => (
            <div key={item.band} className="card">
              <Tag tone={item.band === "High" ? "accent-2" : item.band === "Medium" ? "accent" : "neutral"}>{item.band}</Tag>
              <div className="card-body">{item.body}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="card" style={{ background: "var(--color-accent-100)", border: "none" }}>
        <div className="card-kicker" style={{ color: "var(--color-accent-900)" }}>Known limits</div>
        <div className="card-body" style={{ color: "var(--color-accent-900)" }}>
          The base covers a small hand-vetted cohort today. Signal collection is manual by design.
          Fit scores are single-rater assessments, not ground truth — which is why every number
          links back to its criteria, justifications, and adjustment history.
        </div>
      </section>
    </div>
  );
}
