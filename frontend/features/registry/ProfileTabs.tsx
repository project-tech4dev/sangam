"use client";

import Link from "next/link";
import { EntityMark, ProgressBar, StatRail } from "@/components/ui";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type {
  Contact, FunderDetail, GrantRow, NewsRow, OrgDetail, ProgramRow, ScoreRow,
} from "@/lib/api";
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

const KICKER = "text-xs font-bold tracking-widest uppercase text-muted-foreground";

function SectionCard({ kicker, title, children }: { kicker?: string; title?: string; children: React.ReactNode }) {
  return (
    <Card className="gap-4">
      {(kicker || title) && (
        <CardHeader>
          {kicker && <div className={KICKER}>{kicker}</div>}
          {title && <CardTitle className="text-base font-bold">{title}</CardTitle>}
        </CardHeader>
      )}
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function DegradedNote({ children }: { children: React.ReactNode }) {
  return <p className="m-0 text-sm text-sand-600 italic">{children}</p>;
}

function ProfileTabList({ tabs }: { tabs: { id: string; label: string }[] }) {
  return (
    <TabsList className="max-w-full flex-wrap group-data-horizontal/tabs:h-auto">
      {tabs.map((tab) => (
        <TabsTrigger key={tab.id} value={tab.id}>{tab.label}</TabsTrigger>
      ))}
    </TabsList>
  );
}

function Person({ name, role }: { name: string; role: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <EntityMark name={name} size={34} />
      <div>
        <div className="text-sm font-bold">{name}</div>
        <div className="text-xs text-sand-500">{role}</div>
      </div>
    </div>
  );
}

function GrantLine({ grant, href, name, divided }: { grant: GrantRow; href: string; name: string | null; divided?: boolean }) {
  return (
    <div className={cn("flex flex-wrap items-baseline gap-2.5 text-sm", divided && "border-t pt-2")}>
      <Link href={href} className="font-bold">{name}</Link>
      <span className="text-muted-foreground">{grant.title}</span>
      <Badge variant={grant.status === "active" ? "secondary" : "outline"}>{grant.status}</Badge>
      <span className="text-xs text-sand-500">
        {[fmtDate(grant.start_date), fmtDate(grant.end_date)].filter(Boolean).join(" – ") || "dates not public"} · {fmtAmount(grant)}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ org --- */

export function OrgProfileTabs({
  org, grants, programs, scores, news,
}: {
  org: OrgDetail; grants: GrantRow[]; programs: ProgramRow[]; scores: ScoreRow[]; news: NewsRow[];
}) {
  const completenessParts = [
    org.identifiers.length > 0, org.contacts.length > 0, org.tags.length > 0,
    org.locations.length > 0, programs.length > 0, grants.length > 0,
  ];
  const coverage = Math.round((completenessParts.filter(Boolean).length / completenessParts.length) * 100);

  return (
    <Tabs defaultValue="diligence" className="gap-4.5">
      <ProfileTabList
        tabs={[
          { id: "diligence", label: "Diligence" },
          { id: "programs", label: "Programs & taxonomy" },
          { id: "scores", label: "Fit scores" },
          { id: "geography", label: "Geography" },
          { id: "signals", label: "Signals" },
        ]}
      />

      <TabsContent value="diligence" className="flex flex-col gap-4">
        <SectionCard kicker="Base coverage" title={`${coverage} / 100`}>
          <div className="flex flex-col gap-2.5">
            <ProgressBar pct={coverage} color={coverage >= 65 ? "var(--color-accent-2-600)" : "var(--color-accent-600)"} />
            <p className="m-0 text-xs text-muted-foreground">
              Share of profile sections with verified data in the base — not a judgement of the organisation.
            </p>
          </div>
        </SectionCard>

        <SectionCard kicker="Credentials" title="Registrations on file">
          <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3">
            {EXPECTED_IDS.map((idType) => {
              const found = org.identifiers.find((i) => i.id_type === idType);
              return (
                <div key={idType} className="flex flex-col gap-1 rounded-lg border bg-background p-3.5">
                  <div className="flex items-center gap-1.5 text-xs font-bold">
                    <span className={cn("size-2 rounded-full", found ? "bg-sage-600" : "bg-sand-400")} />
                    {found ? "Verified" : "Not entered"}
                    <span className="ml-auto text-sand-500">{ID_LABELS[idType]}</span>
                  </div>
                  <div className={cn("text-sm font-bold", found ? "text-foreground" : "text-sand-500 italic")}>
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
            <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-2.5">
              {org.contacts.slice(0, 8).map((person: Contact) => (
                <Person key={person.id} name={person.name} role={person.role ?? person.kind} />
              ))}
            </div>
          )}
          {org.contacts.length > 8 && (
            <div className="mt-2.5 text-xs text-sand-500">+ {org.contacts.length - 8} more on record</div>
          )}
        </SectionCard>

        <SectionCard kicker="Known funders" title="Funding relationships in the base">
          {grants.length === 0 ? (
            <DegradedNote>No funding relationships recorded yet — awaiting research or vetting.</DegradedNote>
          ) : (
            <div className="flex flex-col gap-2.5">
              {grants.map((grant) => (
                <GrantLine key={grant.id} grant={grant} href={`/registry/funders/${grant.funder_id}`} name={grant.funder_name} />
              ))}
            </div>
          )}
        </SectionCard>
      </TabsContent>

      <TabsContent value="programs" className="flex flex-col gap-4">
        <SectionCard kicker="Sector footprint" title="Tagged sectors">
          {org.tags.length === 0 ? (
            <DegradedNote>No sector tags yet.</DegradedNote>
          ) : (
            <div className="flex flex-wrap gap-2">
              {org.tags.map((t) => (
                <Badge key={t.slug} variant={t.role === "primary" ? "secondary" : "outline"}>
                  {t.label}{t.role === "secondary" ? " · secondary" : ""}
                </Badge>
              ))}
            </div>
          )}
        </SectionCard>
        {programs.length === 0 ? (
          <SectionCard kicker="Programs" title="No programs mapped yet">
            <DegradedNote>Program mapping happens during vetting — nothing invented in the meantime.</DegradedNote>
          </SectionCard>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-3.5">
            {programs.map((program) => (
              <SectionCard key={program.id} kicker={program.status ?? "program"} title={program.name}>
                {program.description && <p className="m-0 text-sm text-muted-foreground">{program.description}</p>}
              </SectionCard>
            ))}
          </div>
        )}
      </TabsContent>

      <TabsContent value="scores" className="flex flex-col gap-3.5">
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
      </TabsContent>

      <TabsContent value="geography" className="flex flex-col gap-4">
        <SectionCard kicker="Where they work" title="Locations in the base">
          {org.locations.length === 0 ? (
            <DegradedNote>— not yet entered</DegradedNote>
          ) : (
            <div className="flex flex-wrap gap-2">
              {org.locations.map((loc) => (
                <Badge key={loc.id} variant="outline">{loc.name} · {loc.kind}</Badge>
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
      </TabsContent>

      <TabsContent value="signals">
        <SectionCard kicker="In the news" title="Signals collected">
          {news.length === 0 ? (
            <DegradedNote>No signal collected for this organisation yet.</DegradedNote>
          ) : (
            <div className="flex flex-col gap-2">
              {news.map((item) => (
                <div key={item.id} className="flex flex-wrap items-baseline gap-2.5 border-t pt-2">
                  <a href={item.url} target="_blank" rel="noreferrer" className="text-sm font-bold">
                    {item.title ?? item.url}
                  </a>
                  <span className="text-xs text-sand-500">
                    {item.domain} · {fmtDate(item.seendate) ?? "date unknown"}
                  </span>
                  <Badge variant="outline">Pending review</Badge>
                </div>
              ))}
            </div>
          )}
        </SectionCard>
      </TabsContent>
    </Tabs>
  );
}

/* --------------------------------------------------------------- funder --- */

export function FunderProfileTabs({
  funder, scores, grants, news,
}: {
  funder: FunderDetail; scores: ScoreRow[]; grants: GrantRow[]; news: NewsRow[];
}) {
  const profileEntries = Object.entries(funder.profile ?? {}).filter(([, v]) => typeof v === "string");
  const scoredOrgs = new Set(scores.map((s) => s.org_id)).size;

  return (
    <Tabs defaultValue="mandate" className="gap-4.5">
      <ProfileTabList
        tabs={[
          { id: "mandate", label: "Mandate & priorities" },
          { id: "giving", label: "Giving pattern" },
          { id: "matches", label: "Matched CSOs" },
          { id: "contacts", label: "Contacts" },
        ]}
      />

      <TabsContent value="mandate" className="flex flex-col gap-4">
        <SectionCard kicker="Stated focus" title="Sectors this funder names">
          <div className="flex flex-wrap gap-2">
            {funder.focus_sectors.map((s) => <Badge key={s} variant="secondary">{s}</Badge>)}
          </div>
        </SectionCard>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-3.5">
          <SectionCard kicker="Geography" title="Where they fund">
            <div className="flex flex-wrap gap-1.5">
              {funder.geographies.map((g) => <Badge key={g} variant="outline">{g}</Badge>)}
            </div>
          </SectionCard>
          <SectionCard kicker="What we know" title="Profile facts">
            {profileEntries.length === 0 ? (
              <DegradedNote>— not yet entered</DegradedNote>
            ) : (
              <div className="flex flex-col gap-1.5">
                {profileEntries.map(([key, value]) => (
                  <div key={key} className="text-xs">
                    <strong className="capitalize">{key.replace(/_/g, " ")}:</strong>{" "}
                    <span className="text-muted-foreground">{String(value)}</span>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>
        </div>
      </TabsContent>

      <TabsContent value="giving">
        <SectionCard kicker="Recorded grants" title="Where grants have landed">
          {grants.length === 0 ? (
            <DegradedNote>No grants recorded for this funder yet.</DegradedNote>
          ) : (
            <div className="flex flex-col gap-2">
              {grants.map((grant) => (
                <GrantLine key={grant.id} grant={grant} href={`/registry/${grant.org_id}`} name={grant.org_name} divided />
              ))}
            </div>
          )}
        </SectionCard>
      </TabsContent>

      <TabsContent value="matches" className="flex flex-col gap-3.5">
        <Card className="bg-secondary py-3.5 text-secondary-foreground shadow-none ring-0">
          <CardContent className="text-sm">
            Only organisations that have been hand-scored appear here — {scoredOrgs} of 10 in the cohort today.
          </CardContent>
        </Card>
        {scores.length === 0 ? (
          <SectionCard title="No scored matches yet">
            <DegradedNote>No cohort organisation has been scored against this funder&apos;s rubric yet.</DegradedNote>
          </SectionCard>
        ) : (
          scores.map((score) => (
            <ScoreCard key={score.id} score={score} headline={`${score.org_name}`} />
          ))
        )}
      </TabsContent>

      <TabsContent value="contacts">
        <SectionCard kicker="People" title="Contacts on record">
          {funder.contacts.length === 0 ? (
            <DegradedNote>No named contacts in the base — outreach route not yet mapped.</DegradedNote>
          ) : (
            <div className="flex flex-col gap-2.5">
              {funder.contacts.map((person) => (
                <Person key={person.id} name={person.name} role={person.role ?? person.kind} />
              ))}
            </div>
          )}
        </SectionCard>
      </TabsContent>
    </Tabs>
  );
}
