"use client";

import Link from "next/link";
import { useState } from "react";
import { PillTabs } from "../../components/PillTabs";
import { EntityMark, ProgressBar, StatRail, Tag } from "../../components/ui";
import type {
  Contact, FunderDetail, GrantRow, NewsRow, OrgDetail, ProgramRow, ScoreRow,
} from "../../lib/api";
import { ScoreCard } from "./ScoreCard";

const ID_LABELS: Record<string, string> = {
  pan: "PAN", "12a": "12A", "80g": "80G", fcra: "FCRA", csr1: "CSR Form 1",
  darpan: "NGO Darpan", reg_no: "Registration number", cin: "CIN", domain: "Domain",
};

const EXPECTED_IDS = ["pan", "12a", "80g", "fcra", "csr1", "darpan", "reg_no"];

function fmtDate(value: string | null): string | null {
  if (!value) return null;
  return new Date(value).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function fmtAmount(grant: GrantRow): string {
  if (grant.amount == null) return "amount not public";
  return `₹${Number(grant.amount).toLocaleString("en-IN")}`;
}

function SectionCard({ kicker, title, children }: { kicker?: string; title?: string; children: React.ReactNode }) {
  return (
    <div className="card">
      {kicker && <div className="card-kicker">{kicker}</div>}
      {title && <div className="card-title">{title}</div>}
      {children}
    </div>
  );
}

function DegradedNote({ children }: { children: React.ReactNode }) {
  return <div className="card-body" style={{ fontStyle: "italic", color: "var(--color-neutral-600)" }}>{children}</div>;
}

/* ------------------------------------------------------------------ org --- */

export function OrgProfileTabs({
  org, grants, programs, scores, news,
}: {
  org: OrgDetail; grants: GrantRow[]; programs: ProgramRow[]; scores: ScoreRow[]; news: NewsRow[];
}) {
  const [tab, setTab] = useState("diligence");
  const completenessParts = [
    org.identifiers.length > 0, org.contacts.length > 0, org.tags.length > 0,
    org.locations.length > 0, programs.length > 0, grants.length > 0,
  ];
  const coverage = Math.round((completenessParts.filter(Boolean).length / completenessParts.length) * 100);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <PillTabs
        tabs={[
          { id: "diligence", label: "Diligence" },
          { id: "programs", label: "Programs & taxonomy" },
          { id: "scores", label: "Fit scores" },
          { id: "geography", label: "Geography" },
          { id: "signals", label: "Signals" },
        ]}
        active={tab}
        onPick={setTab}
      />

      {tab === "diligence" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <SectionCard kicker="Base coverage" title={`${coverage} / 100`}>
            <ProgressBar pct={coverage} color={coverage >= 65 ? "var(--color-accent-2-600)" : "var(--color-accent-600)"} />
            <div className="card-body" style={{ fontSize: 12 }}>
              Share of profile sections with verified data in the base — not a judgement of the organisation.
            </div>
          </SectionCard>

          <SectionCard kicker="Credentials" title="Registrations on file">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 12 }}>
              {EXPECTED_IDS.map((idType) => {
                const found = org.identifiers.find((i) => i.id_type === idType);
                return (
                  <div key={idType} className="card" style={{ padding: 14, gap: 4 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, fontWeight: 600 }}>
                      <span
                        style={{
                          width: 8, height: 8, borderRadius: "50%",
                          background: found ? "var(--color-accent-2-600)" : "var(--color-neutral-400)",
                        }}
                      />
                      {found ? "Verified" : "Not entered"}
                      <span className="muted-2" style={{ marginLeft: "auto" }}>{ID_LABELS[idType]}</span>
                    </div>
                    <div style={{ fontSize: 13, fontWeight: 600, fontStyle: found ? "normal" : "italic", color: found ? "var(--color-text)" : "var(--color-neutral-500)" }}>
                      {found ? found.id_value : "— not in base"}
                    </div>
                  </div>
                );
              })}
            </div>
          </SectionCard>

          <SectionCard kicker="Who's accountable" title="People on record">
            {org.contacts.length === 0 ? (
              <DegradedNote>— not yet entered</DegradedNote>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
                {org.contacts.slice(0, 8).map((person: Contact) => (
                  <div key={person.id} style={{ display: "flex", gap: 10, alignItems: "center" }}>
                    <EntityMark name={person.name} size={34} />
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600 }}>{person.name}</div>
                      <div className="muted-2" style={{ fontSize: 11.5 }}>{person.role ?? person.kind}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {org.contacts.length > 8 && (
              <div className="muted-2" style={{ fontSize: 12 }}>+ {org.contacts.length - 8} more on record</div>
            )}
          </SectionCard>

          <SectionCard kicker="Known funders" title="Funding relationships in the base">
            {grants.length === 0 ? (
              <DegradedNote>No funding relationships recorded yet — awaiting research or vetting.</DegradedNote>
            ) : (
              grants.map((grant) => (
                <div key={grant.id} style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap", fontSize: 13 }}>
                  <Link href={`/registry/funders/${grant.funder_id}`} style={{ fontWeight: 600 }}>
                    {grant.funder_name}
                  </Link>
                  <span className="muted">{grant.title}</span>
                  <Tag tone={grant.status === "active" ? "accent-2" : "neutral"}>{grant.status}</Tag>
                  <span className="muted-2" style={{ fontSize: 11.5 }}>
                    {[fmtDate(grant.start_date), fmtDate(grant.end_date)].filter(Boolean).join(" – ") || "dates not public"} · {fmtAmount(grant)}
                  </span>
                </div>
              ))
            )}
          </SectionCard>
        </div>
      )}

      {tab === "programs" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <SectionCard kicker="Sector footprint" title="Tagged sectors">
            {org.tags.length === 0 ? (
              <DegradedNote>No sector tags yet.</DegradedNote>
            ) : (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {org.tags.map((t) => (
                  <Tag key={t.slug} tone={t.role === "primary" ? "accent-2" : "outline"}>
                    {t.label}{t.role === "secondary" ? " · secondary" : ""}
                  </Tag>
                ))}
              </div>
            )}
          </SectionCard>
          {programs.length === 0 ? (
            <SectionCard kicker="Programs" title="No programs mapped yet">
              <DegradedNote>Program mapping happens during vetting — nothing invented in the meantime.</DegradedNote>
            </SectionCard>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 14 }}>
              {programs.map((program) => (
                <div key={program.id} className="card">
                  <div className="card-kicker">{program.status ?? "program"}</div>
                  <div className="card-title" style={{ fontSize: 15 }}>{program.name}</div>
                  {program.description && <div className="card-body">{program.description}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "scores" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {scores.length === 0 ? (
            <SectionCard title="No fit scores recorded">
              <DegradedNote>
                This organisation has not yet been scored against a funder rubric. Scores appear here
                once a hand-vetted (or model-assisted) assessment lands in the base.
              </DegradedNote>
            </SectionCard>
          ) : (
            scores.map((score) => (
              <ScoreCard key={score.id} score={score} headline={`${score.funder_name}`} />
            ))
          )}
        </div>
      )}

      {tab === "geography" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <SectionCard kicker="Where they work" title="Locations in the base">
            {org.locations.length === 0 ? (
              <DegradedNote>— not yet entered</DegradedNote>
            ) : (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {org.locations.map((loc) => (
                  <Tag key={loc.id} tone="outline">{loc.name} · {loc.kind}</Tag>
                ))}
              </div>
            )}
          </SectionCard>
          <SectionCard>
            <StatRail
              stats={[
                { value: org.locations.filter((l) => l.kind === "district").length || null, label: "Districts" },
                { value: new Set(org.locations.map(() => org.state).filter(Boolean)).size || (org.state ? 1 : null), label: "States" },
                { value: null, label: "Villages" },
                { value: null, label: "Families reached" },
              ]}
            />
          </SectionCard>
        </div>
      )}

      {tab === "signals" && (
        <SectionCard kicker="In the news" title="Signals collected">
          {news.length === 0 ? (
            <DegradedNote>No signal collected for this organisation yet.</DegradedNote>
          ) : (
            news.map((item) => (
              <div key={item.id} style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap", borderTop: "1px solid var(--color-divider)", paddingTop: 8 }}>
                <a href={item.url} target="_blank" rel="noreferrer" style={{ fontSize: 13, fontWeight: 600 }}>
                  {item.title ?? item.url}
                </a>
                <span className="muted-2" style={{ fontSize: 11.5 }}>
                  {item.domain} · {fmtDate(item.seendate) ?? "date unknown"}
                </span>
                <Tag tone="neutral">Pending review</Tag>
              </div>
            ))
          )}
        </SectionCard>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- funder --- */

export function FunderProfileTabs({
  funder, scores, grants, news,
}: {
  funder: FunderDetail; scores: ScoreRow[]; grants: GrantRow[]; news: NewsRow[];
}) {
  const [tab, setTab] = useState("mandate");
  const profileEntries = Object.entries(funder.profile ?? {}).filter(([, v]) => typeof v === "string");
  const scoredOrgs = new Set(scores.map((s) => s.org_id)).size;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <PillTabs
        tabs={[
          { id: "mandate", label: "Mandate & priorities" },
          { id: "giving", label: "Giving pattern" },
          { id: "matches", label: "Matched CSOs" },
          { id: "contacts", label: "Contacts" },
        ]}
        active={tab}
        onPick={setTab}
      />

      {tab === "mandate" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <SectionCard kicker="Stated focus" title="Sectors this funder names">
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {funder.focus_sectors.map((s) => <Tag key={s} tone="accent-2">{s}</Tag>)}
            </div>
          </SectionCard>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 14 }}>
            <SectionCard kicker="Geography" title="Where they fund">
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {funder.geographies.map((g) => <Tag key={g} tone="outline">{g}</Tag>)}
              </div>
            </SectionCard>
            <SectionCard kicker="What we know" title="Profile facts">
              {profileEntries.length === 0 ? (
                <DegradedNote>— not yet entered</DegradedNote>
              ) : (
                profileEntries.map(([key, value]) => (
                  <div key={key} style={{ fontSize: 12.5 }}>
                    <strong style={{ textTransform: "capitalize" }}>{key.replace(/_/g, " ")}:</strong>{" "}
                    <span className="muted">{String(value)}</span>
                  </div>
                ))
              )}
            </SectionCard>
          </div>
        </div>
      )}

      {tab === "giving" && (
        <SectionCard kicker="Recorded grants" title="Where grants have landed">
          {grants.length === 0 ? (
            <DegradedNote>No grants recorded for this funder yet.</DegradedNote>
          ) : (
            grants.map((grant) => (
              <div key={grant.id} style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap", borderTop: "1px solid var(--color-divider)", paddingTop: 8, fontSize: 13 }}>
                <Link href={`/registry/${grant.org_id}`} style={{ fontWeight: 600 }}>{grant.org_name}</Link>
                <span className="muted">{grant.title}</span>
                <Tag tone={grant.status === "active" ? "accent-2" : "neutral"}>{grant.status}</Tag>
                <span className="muted-2" style={{ fontSize: 11.5 }}>
                  {[fmtDate(grant.start_date), fmtDate(grant.end_date)].filter(Boolean).join(" – ") || "dates not public"} · {fmtAmount(grant)}
                </span>
              </div>
            ))
          )}
        </SectionCard>
      )}

      {tab === "matches" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card" style={{ background: "var(--color-accent-2-100)", border: "none", padding: 14 }}>
            <div className="card-body" style={{ color: "var(--color-accent-2-900)" }}>
              Only organisations that have been hand-scored appear here — {scoredOrgs} of 10 in the cohort today.
            </div>
          </div>
          {scores.length === 0 ? (
            <SectionCard title="No scored matches yet">
              <DegradedNote>No cohort organisation has been scored against this funder&apos;s rubric yet.</DegradedNote>
            </SectionCard>
          ) : (
            scores.map((score) => (
              <ScoreCard key={score.id} score={score} headline={`${score.org_name}`} />
            ))
          )}
        </div>
      )}

      {tab === "contacts" && (
        <SectionCard kicker="People" title="Contacts on record">
          {funder.contacts.length === 0 ? (
            <DegradedNote>No named contacts in the base — outreach route not yet mapped.</DegradedNote>
          ) : (
            funder.contacts.map((person) => (
              <div key={person.id} style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <EntityMark name={person.name} size={34} />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{person.name}</div>
                  <div className="muted-2" style={{ fontSize: 11.5 }}>{person.role ?? person.kind}</div>
                </div>
              </div>
            ))
          )}
        </SectionCard>
      )}
    </div>
  );
}
