import Link from "next/link";
import type { ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { EligibilityDoc, FunderIdentity, OpenCall, ProgramNode } from "@/lib/api";
import { dayMonthYear, funderTypeLabel } from "@/lib/format";
import { Card, count, Empty, humanise, inr, ProgramTree, PTag, safeHref, SourceLink } from "./shared";

function identityRows(f: FunderIdentity) {
  const rows: { label: string; value: ReactNode }[] = [];
  if (f.funder_type) rows.push({ label: "Type", value: funderTypeLabel(f.funder_type) });
  if (f.legal_form || f.founded_year) {
    rows.push({ label: "Legal form", value: [f.legal_form, f.founded_year && `formed ${f.founded_year}`].filter(Boolean).join(", ") });
  }
  if (f.parent) {
    rows.push({ label: "Part of", value: <Link href={`/registry/funders/${f.parent.slug}`}>{f.parent.name}</Link> });
  }
  if (f.registered_address || f.registered_location) {
    rows.push({ label: "Registered", value: [f.registered_address, f.registered_location].filter(Boolean).join(" · ") });
  }
  if (f.cin) rows.push({ label: "CIN", value: f.cin });
  if (f.section_135_bound != null) {
    rows.push({ label: "Section 135", value: f.section_135_bound ? "Bound by the CSR law" : "Not bound by the CSR law" });
  }
  if (f.intake_mode) rows.push({ label: "Takes partners by", value: humanise(f.intake_mode) });
  if (f.funds_external != null) {
    rows.push({ label: "Funds others", value: f.funds_external ? "Yes, through partner organisations" : "No, runs its own work" });
  }
  if (f.grant_size_min != null || f.grant_size_max != null) {
    rows.push({ label: "Grant size", value: `${inr(f.grant_size_min)} – ${inr(f.grant_size_max)}` });
  }
  if (f.typical_duration_months != null) rows.push({ label: "Typical duration", value: `${f.typical_duration_months} months` });
  if (f.aliases.length) rows.push({ label: "Also known as", value: f.aliases.join(" · ") });
  return rows;
}

export function FunderMandate({
  funder, eligibility, openCalls, programs, hiddenContacts,
}: {
  funder: FunderIdentity; eligibility: EligibilityDoc[]; openCalls: OpenCall[]; programs: ProgramNode[];
  hiddenContacts: number;
}) {
  const identity = identityRows(funder);
  // Shown by role, so two rows with the same role and address read as one.
  const contacts = [...new Map(funder.contacts.map((c) => [`${c.role ?? c.name}|${c.email ?? ""}`, c])).values()];
  return (
    <div className="profile-tab">
      <Card kicker="Identity">
        {identity.length === 0 ? <Empty>No identity facts recorded yet.</Empty> : identity.map((row) => (
          <div key={row.label} className="profile-line">
            <div className="profile-row">
              <span className="profile-label">{row.label}</span>
              <strong>{row.value}</strong>
              <SourceLink url={funder.source_url} />
            </div>
          </div>
        ))}
      </Card>

      <Card kicker="How it picks partners">
        {eligibility.length === 0 && openCalls.length === 0 && <Empty>No eligibility or open call recorded yet.</Empty>}
        {eligibility.map((e) => (
          <div key={e.id} className="profile-tab">
            {e.content_md && (
              // The funder's wording under the headings Import writes; never raw HTML.
              <div className="answer-md profile-md profile-quote">
                <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml urlTransform={defaultUrlTransform}
                  components={{ h2: ({ children }) => <div className="card-kicker">{children}</div> }}>
                  {e.content_md}
                </ReactMarkdown>
              </div>
            )}
            <div className="profile-row"><SourceLink url={e.source_url} /></div>
          </div>
        ))}
        {eligibility.length > 0 && openCalls.length === 0 && <div className="profile-row"><PTag>No open call found</PTag></div>}
        {openCalls.map((c) => {
          const href = safeHref(c.url ?? c.source_url);
          return (
            <div key={c.id} className="profile-line">
              <div className="profile-row">
                <PTag>Open call</PTag>
                {href ? <a href={href} target="_blank" rel="noopener noreferrer" className="profile-strong">{c.title} ↗</a>
                  : <strong>{c.title}</strong>}
                {c.deadline && <span className="muted">closes {dayMonthYear(c.deadline)}</span>}
                {(c.amount_min != null || c.amount_max != null) && (
                  <span className="muted">{inr(c.amount_min)} – {inr(c.amount_max)}</span>
                )}
              </div>
            </div>
          );
        })}
      </Card>

      <Card kicker="Programmes">
        {/* A funder's figures have their own table under Reach. */}
        <ProgramTree programs={programs} metrics={false} kinds />
      </Card>

      <Card kicker="How to reach them">
        {contacts.length === 0 && hiddenContacts === 0 && <Empty>No public contacts yet.</Empty>}
        {contacts.map((c) => (
          <div key={c.id} className="profile-row">
            <strong>{c.role ?? c.name}</strong>
            {c.email && <span className="muted">{c.email}</span>}
            <SourceLink url={c.source_url} />
          </div>
        ))}
        {hiddenContacts > 0 && (
          <div className="muted profile-sm">
            {count(hiddenContacts, "named office-bearer")} {hiddenContacts === 1 ? "is" : "are"} on file and not shown publicly.
          </div>
        )}
      </Card>
    </div>
  );
}
