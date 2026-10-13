import type { ReactNode } from "react";
import { formatInr, monthYear } from "@/lib/format";
import type { ProgramNode, TagNote } from "@/lib/api";

/* Catalog URLs come from web research: only an http(s) URL becomes a link. */
export function safeHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

export function hostOf(url: string | null | undefined): string {
  const href = safeHref(url);
  return href ? new URL(href).hostname.replace(/^www\./, "") : "";
}

const AGGREGATORS = ["give.do", "guidestarindia.org", "guidestarindia.frappe.cloud"];

/* What kind of page a source is, judged from its address alone. */
export function sourceKind(url: string): string {
  const host = hostOf(url);
  if (url.includes("org-grant-intelligence")) return "earlier research";
  if (AGGREGATORS.includes(host)) return "aggregator";
  if (host.endsWith("gov.in") || host.endsWith("nic.in")) return "registry";
  return "source";
}

export function sourceLabel(url: string): string {
  return sourceKind(url) === "earlier research" ? "Sangam's earlier research" : hostOf(url);
}

/* The source chip beside a fact, labelled by the site it came from. */
export function SourceLink({ url, label }: { url: string | null | undefined; label?: string | null }) {
  const href = safeHref(url);
  if (!href) return null;
  return (
    <a className="profile-src" href={href} target="_blank" rel="noopener noreferrer">
      {label || sourceLabel(href)} ↗
    </a>
  );
}

/* A table's source cell: the source's own name, kept short. */
export function shortSource(name: string | null | undefined, url: string | null | undefined): string {
  const research = url && sourceKind(url) === "earlier research";
  const text = (research ? sourceLabel(url) : name || sourceLabel(url ?? "")).replace("Annual Report", "AR");
  return text.length > 48 ? `${text.slice(0, 47)}…` : text;
}

export function Card({ kicker, aside, children }: { kicker: string; aside?: ReactNode; children?: ReactNode }) {
  return (
    <section className="profile-card">
      {aside ? (
        <div className="profile-row"><div className="profile-kicker">{kicker}</div>{aside}</div>
      ) : (
        <div className="profile-kicker">{kicker}</div>
      )}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="profile-empty">{children}</p>;
}

export function PTag({ children }: { children: ReactNode }) {
  return <span className="profile-tag">{children}</span>;
}

export const inr = (value: number | null) => (value == null ? "—" : formatInr(Number(value)));

export function count(n: number, one: string, many = `${one}s`) {
  return `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;
}

export const humanise = (value: string) => value.replace(/_/g, " ");

export const num = (value: number) => Number(value).toLocaleString("en-IN");

/* Themes read "Theme › Sub-theme"; populations and lenses are who the work is for. */
export function splitTags(tags: TagNote[]) {
  const themes = tags.filter((t) => t.kind === "theme" || t.kind === "sub_theme");
  const who = tags.filter((t) => t.kind === "population" || t.kind === "lens");
  return { themes, who };
}

export const themeLabel = (t: TagNote) => (t.parent_label ? `${t.parent_label} › ${t.label}` : t.label);

/* Programmes as their tree: a phase or component sits indented under its programme. */
export function ProgramTree({ programs, metrics = true, kinds = false }: {
  programs: ProgramNode[]; metrics?: boolean; kinds?: boolean;
}) {
  if (programs.length === 0) return <Empty>No programmes recorded yet.</Empty>;
  const ids = new Set(programs.map((p) => p.id));
  const roots = programs.filter((p) => p.parent_id == null || !ids.has(p.parent_id));
  const rows: { p: ProgramNode; depth: number }[] = [];
  const walk = (p: ProgramNode, depth: number) => {
    rows.push({ p, depth });
    programs.filter((c) => c.parent_id === p.id).forEach((c) => walk(c, depth + 1));
  };
  roots.forEach((p) => walk(p, 0));
  return (
    <>
      {rows.map(({ p, depth }) => (
        <div key={p.id} className={depth ? "profile-line profile-indent" : "profile-line"}>
          <div className="profile-row">
            <strong>{p.name}</strong>
            {kinds && p.kind && <PTag>{humanise(p.kind)}</PTag>}
            {p.start_date && <PTag>from {monthYear(p.start_date)}</PTag>}
            {p.status && <PTag>{humanise(p.status)}</PTag>}
            {kinds && <SourceLink url={p.source_url} />}
          </div>
          {p.description && <span className="muted profile-body">{p.description}</span>}
          {metrics && p.metrics.map((m) => {
            const isTarget = m.value == null && m.target != null;
            const n = m.value ?? m.target;
            return (
              <div key={m.id} className="profile-row profile-metric">
                <strong>{n == null ? "not stated" : num(n)}</strong>
                <span>{m.unit}{isTarget ? " (target)" : ""}</span>
                <span className="muted">{m.name}</span>
              </div>
            );
          })}
          {!kinds && safeHref(p.source_url) && <div><SourceLink url={p.source_url} /></div>}
        </div>
      ))}
    </>
  );
}
