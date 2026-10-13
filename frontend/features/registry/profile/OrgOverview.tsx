import Link from "next/link";
import type { OrgIdentity } from "@/lib/api";
import { monthYear } from "@/lib/format";
import { pickIdentifier, statusLabel, statusTone } from "../identifierStatus";
import { Card, count, Empty, safeHref, SourceLink } from "./shared";

export const ID_LABELS: Record<string, string> = {
  pan: "PAN", "12a": "12A", "80g": "80G", fcra: "FCRA", csr1: "CSR Form 1",
  darpan: "NGO Darpan", reg_no: "Registration no.", cin: "CIN", domain: "Domain",
};

const ID_ORDER = ["pan", "reg_no", "12a", "fcra", "80g", "csr1", "darpan"];

export const SOURCE_TYPES: Record<string, string> = {
  registry: "government registry", org_document: "organisation's document", funder: "funder",
  staff_dataset: "Sangam's team", manual_check: "manual check", prior_research: "earlier research",
  aggregator: "aggregator", seed: "seed data",
};

export function OrgOverview({ org, hiddenContacts }: { org: OrgIdentity; hiddenContacts: number }) {
  const identity: { label: string; value: React.ReactNode }[] = [];
  if (org.legal_form) identity.push({ label: "Legal form", value: org.legal_form });
  if (org.registration_date) identity.push({ label: "Registered", value: monthYear(org.registration_date, true) });
  if (org.aliases.length) identity.push({ label: "Also known as", value: org.aliases.join(" · ") });
  if (org.parent) {
    identity.push({ label: "Part of", value: <Link href={`/registry/${org.parent.slug}`}>{org.parent.name}</Link> });
  }
  if (org.staff_count != null) {
    identity.push({ label: "Staff", value: `${org.staff_count}${org.staff_count_note ? ` — ${org.staff_count_note}` : ""}` });
  }
  const types = [...new Set([...ID_ORDER, ...org.identifiers.map((i) => i.id_type)])]
    .filter((t) => org.identifiers.some((i) => i.id_type === t));
  const shown = types.map((t) => pickIdentifier(org.identifiers, t)!);
  const website = safeHref(org.website);

  return (
    <div className="profile-tab">
      <Card kicker="Identity">
        {identity.length === 0 ? <Empty>No identity facts recorded yet.</Empty> : identity.map((row) => (
          <div key={row.label} className="profile-line">
            <div className="profile-row">
              <span className="profile-label">{row.label}</span>
              <strong>{row.value}</strong>
              <SourceLink url={org.source_url} />
            </div>
          </div>
        ))}
      </Card>

      <Card kicker={`Registrations · ${shown.length}`}>
        {shown.length === 0 ? <Empty>No registrations on file yet.</Empty> : (
          <div className="profile-grid profile-grid-ids">
            {shown.map((id) => {
              const value = id.id_value ?? (id.application_ref ? `application ${id.application_ref}` : null);
              return (
                <div key={id.id_type} className="profile-id">
                  <div className="profile-id-head">
                    <span className="profile-dot" data-tone={statusTone(id)} />
                    {statusLabel(id).replace(" (claimed)", "")}
                    <span className="card-kicker profile-id-type">{ID_LABELS[id.id_type] ?? id.id_type}</span>
                  </div>
                  <div className="profile-id-value">
                    {value ?? <span className="muted">{id.number_withheld ? "on file, not published" : "no number recorded"}</span>}
                  </div>
                  <div className="profile-row">
                    {id.source_type && (
                      <span className="profile-note">
                        {id.evidence ?? "recorded"} by {SOURCE_TYPES[id.source_type] ?? id.source_type}
                      </span>
                    )}
                    <SourceLink url={id.source_url} />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <Card kicker="How to reach them">
        {!org.registered_address && org.contacts.length === 0 && !website && hiddenContacts === 0 && (
          <Empty>No public contact details yet.</Empty>
        )}
        {org.registered_address && (
          <div className="profile-line">
            <div className="profile-row"><strong>Head office</strong><span>{org.registered_address}</span></div>
          </div>
        )}
        {org.contacts.map((c) => (
          <div key={c.id} className="profile-line">
            <div className="profile-row">
              <strong>{c.name}</strong>
              {c.role && <span>{c.role}</span>}
              {c.email && <span className="muted">{c.email}</span>}
              {c.phone && <span className="muted">{c.phone}</span>}
              <SourceLink url={c.source_url} />
            </div>
          </div>
        ))}
        {website && (
          <div className="profile-line">
            <div className="profile-row">
              <strong>Website</strong>
              <a href={website} target="_blank" rel="noopener noreferrer">{website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")} ↗</a>
            </div>
          </div>
        )}
        {hiddenContacts > 0 && (
          <div className="profile-note">
            {count(hiddenContacts, "office-bearer")} {hiddenContacts === 1 ? "is" : "are"} on file and not shown publicly.
          </div>
        )}
      </Card>
    </div>
  );
}
