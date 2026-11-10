"use client";

import Link from "next/link";
import { ListMore } from "@/components/ui";
import type { CsrYear, EntityRef, PartnerGroupPage, ProgramNode, SpendLine } from "@/lib/api";
import { distinctLines, usePartnerGroups } from "./partnerGroups";
import { Card, Empty, inr, PTag, shortSource, SourceLink } from "./shared";

type SpendRow = { key: string; label: string; cells: Map<string, SpendLine> };

/* One row per programme; a second line for the same programme and year opens another row rather than being lost. */
export function spendRows(spend: SpendLine[]): SpendRow[] {
  const rows: SpendRow[] = [];
  let unnamed = 0;
  for (const line of [...spend].sort((a, b) => a.id - b.id)) {
    const key = line.program_id != null ? `p${line.program_id}` : line.program_name ? `n${line.program_name}` : `l${line.id}`;
    const row = rows.find((r) => r.key === key && !r.cells.has(line.fiscal_year));
    if (row) {
      row.cells.set(line.fiscal_year, line);
      continue;
    }
    const twins = rows.filter((r) => r.key === key).length;
    const base = line.program_name ?? `Unnamed component ${++unnamed}`;
    rows.push({ key, label: twins ? `${base} (${twins + 1})` : base, cells: new Map([[line.fiscal_year, line]]) });
  }
  return rows;
}

/* Spend by programme component and year; the programme's own total, when its components are listed, is the last row. */
function SpendTable({ spend, programs }: { spend: SpendLine[]; programs: ProgramNode[] }) {
  const years = [...new Set(spend.map((s) => s.fiscal_year))].sort();
  const parentOf = new Map(programs.map((p) => [p.id, p.parent_id]));
  const rows = spendRows(spend);
  const isRoot = (r: SpendRow) => r.key.startsWith("p") && !parentOf.get(Number(r.key.slice(1)));
  const roots = rows.filter(isRoot);
  const total = roots.length === 1 && rows.length > 1 ? roots[0] : null;
  const ordered = total ? [...rows.filter((r) => r !== total), total] : rows;
  const sources = [...new Map(spend.filter((s) => s.source_url).map((s) => [s.source_url, s])).values()];
  return (
    <>
      <div className="profile-table-wrap">
        <table className="profile-table">
          <thead><tr><th>{total ? total.label : "Programme"}</th>{years.map((y) => <th key={y}>{y}</th>)}</tr></thead>
          <tbody>
            {ordered.map((row) => (
              <tr key={`${row.key}-${row.label}`} className={row === total ? "profile-total" : undefined}>
                <td>{row === total ? "Total" : row.label}</td>
                {years.map((y) => <td key={y} className="profile-num">{inr(row.cells.get(y)?.amount ?? null)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="profile-row">
        {sources.map((s) => <SourceLink key={s.id} url={s.source_url} label={shortSource(s.source_name, s.source_url)} />)}
      </div>
    </>
  );
}

export function FunderGiving({
  slug, spend, csrYears, partners, programs, parent,
}: {
  slug: string; spend: SpendLine[]; csrYears: CsrYear[]; partners: PartnerGroupPage;
  programs: ProgramNode[]; parent: EntityRef | null;
}) {
  const { groups, busy, more } = usePartnerGroups(partners, `/api/funders/${slug}/partners`);

  return (
    <div className="profile-tab">
      <Card kicker="The foundation's own spend, by programme component">
        {spend.length === 0 ? <Empty>No programme spend recorded yet.</Empty> : <SpendTable spend={spend} programs={programs} />}
      </Card>

      <Card kicker={parent ? `CSR by year · ${parent.name}, the statutory filer` : "CSR by year"}>
        {csrYears.length === 0 ? <Empty>No CSR filings recorded yet.</Empty> : (
          <div className="profile-table-wrap">
            <table className="profile-table">
              <thead>
                <tr><th>Year</th><th>Prescribed</th><th>Spent</th><th>Unspent, transferred</th><th>Source</th></tr>
              </thead>
              <tbody>
                {csrYears.map((c) => (
                  <tr key={c.fiscal_year}>
                    <td>{c.fiscal_year}</td>
                    <td className="profile-num">{c.prescribed_csr == null ? "not read" : inr(c.prescribed_csr)}</td>
                    <td className="profile-num">{c.total_spent == null ? "not read" : inr(c.total_spent)}</td>
                    <td className="profile-num">{inr(c.unspent_transferred)}</td>
                    <td><SourceLink url={c.source_url} label={shortSource(c.source_name, c.source_url)} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        kicker={`Partners · ${partners.total}`}
        aside={partners.total > 0 ? (
          <span className="muted profile-sm">
            {partners.in_registry} in the Registry{partners.has_amounts ? "" : " · no amounts published"}
          </span>
        ) : undefined}
      >
        {partners.total === 0 && <Empty>No partners recorded yet.</Empty>}
        {groups.map((g) => {
          return (
            <div key={g.key} className="profile-line profile-line-tight">
              <div className="profile-row">
                {g.org_slug ? (
                  <Link href={`/registry/${g.org_slug}`} className="profile-strong">{g.name}</Link>
                ) : (
                  <strong>{g.name}</strong>
                )}
              </div>
              {distinctLines(g).map((line) => (
                <div key={line.id} className="profile-row profile-metric">
                  <PTag>{line.fy_is_dated ? line.fiscal_year : "undated"}</PTag>
                  {line.amount != null && <span className="muted">{inr(line.amount)}</span>}
                  {(line.project_name || line.program_name) && (
                    <span className="muted profile-sm">{line.project_name ?? line.program_name}</span>
                  )}
                  <SourceLink url={line.source_url} />
                </div>
              ))}
            </div>
          );
        })}
        {partners.total > groups.length && (
          <ListMore shown={groups.length} total={partners.total} onMore={more} page={20} busy={busy} />
        )}
      </Card>
    </div>
  );
}
