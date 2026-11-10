"use client";

import Link from "next/link";
import { ListMore } from "@/components/ui";
import type { FinancialYear, PartnerGroupPage } from "@/lib/api";
import { distinctLines, usePartnerGroups } from "./partnerGroups";
import { Card, humanise, inr, PTag, shortSource, SourceLink } from "./shared";

export function OrgFunding({ slug, name, funders, financials }: {
  slug: string; name: string; funders: PartnerGroupPage; financials: FinancialYear[];
}) {
  const { groups, busy, more } = usePartnerGroups(funders, `/api/orgs/${slug}/funders`);
  const unconfirmed = groups.some((g) => g.lines.some((l) => l.relationship_status === "unconfirmed"));

  return (
    <div className="profile-tab">
      <Card kicker={`Funders named in sources · ${funders.total}`}>
        {unconfirmed && (
          <p className="profile-blank muted profile-body">
            A relationship stays unconfirmed until the funder&apos;s own record names {name}.
          </p>
        )}
        {funders.total === 0 && <p className="profile-blank">No funders named yet.</p>}
        {groups.map((g) => (
          <div key={g.key} className="profile-line">
            <div className="profile-row">
              <Link href={`/registry/funders/${g.funder_slug}`} className="profile-big">{g.name}</Link>
            </div>
            {distinctLines(g).map((line) => (
              <div key={line.id} className="profile-row profile-metric">
                <PTag>{line.fy_is_dated ? line.fiscal_year : "undated"}</PTag>
                {line.relationship_status && <PTag>{humanise(line.relationship_status)}</PTag>}
                {line.amount != null && <span>{inr(line.amount)}</span>}
                <span className="muted">{(line.notes ?? line.project_name ?? "").split("\n")[0]}</span>
                <SourceLink url={line.source_url} />
              </div>
            ))}
          </div>
        ))}
        {funders.total > groups.length && (
          <ListMore shown={groups.length} total={funders.total} onMore={more} page={20} busy={busy} />
        )}
      </Card>

      <Card kicker="Income and spending">
        {financials.length === 0 ? <p className="profile-blank">No figures found for any year.</p> : (
          <div className="profile-table-wrap">
            <table className="profile-table">
              <thead>
                <tr>
                  <th>Year</th><th>Income</th><th>Programme spend</th><th>Other spend</th>
                  <th>Foreign contribution</th><th>Source</th>
                </tr>
              </thead>
              <tbody>
                {financials.map((f) => (
                  <tr key={f.fiscal_year}>
                    <td>{f.fiscal_year}{f.is_audited ? " · audited" : ""}</td>
                    <td className="profile-num">{inr(f.total_income)}</td>
                    <td className="profile-num">{inr(f.program_spend)}</td>
                    <td className="profile-num">{inr(f.non_program_spend)}</td>
                    <td className="profile-num">{inr(f.foreign_contribution)}</td>
                    <td><SourceLink url={f.source_url} label={shortSource(f.source_name, f.source_url)} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
