"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { BucketCards, FilterRow, initialsOf, ListMore, SearchBox, useShowMore, type Filter } from "@/components/ui";
import { displayName, funderTypeLabel } from "@/lib/format";
import type { RegistryRow } from "@/lib/api";
import { SDG_NAME } from "./sdg";
import {
  DEFAULTS, kindLine, matches, NORTH_EAST, present, signal, type Filters,
} from "./rows";

const PAGE = 20;
const SUB = { all: "Everyone in the Registry", org: "Civil-society organisations", funder: "CSR, foundations, trusts" };

const SHOW = 3;

/* Each domain the row's themes reach, in the order the backend weighed them (most programmes first); Others last. */
function domainsOf(r: RegistryRow): string[] {
  const seen = [...new Set(r.themes.map((t) => t.domain).filter((d): d is string => !!d))];
  return [...seen.filter((d) => d !== "Others"), ...seen.filter((d) => d === "Others")];
}

function More({ n }: { n: number }) {
  return n > 0 ? <span className="reg-more">+{n} more</span> : null;
}

function Row({ r, f }: { r: RegistryRow; f: Filters }) {
  const name = displayName(r.name);
  const domains = domainsOf(r);
  // With a Theme filter set, the row names the sub-themes that put it in the results.
  const matched = f.theme === "all" ? [] : r.themes.filter((t) => t.domain === f.theme).map((t) => t.label);
  const serves = f.population !== "all" && r.populations.includes(f.population)
    ? [f.population, ...r.populations.filter((p) => p !== f.population)] : r.populations;
  return (
    <Link href={r.kind === "org" ? `/registry/${r.slug}` : `/registry/funders/${r.slug}`} className="reg-row">
      <span className="reg-mark" data-kind={r.kind} aria-hidden="true">{initialsOf(name)}</span>
      <span className="reg-row-body">
        <span className="reg-row-head">
          <strong className="reg-row-name">{name}</strong>
          <span className="muted reg-row-kind">{kindLine(r)}</span>
        </span>
        <span className="reg-row-tags">
          {domains.length === 0 && <span className="reg-tag" data-tone="gap">Themes not tagged yet</span>}
          {domains.map((d) => (
            <span key={d} className="reg-tag" data-tone="theme" data-active={d === f.theme || undefined}>{d}</span>
          ))}
          {r.sdgs.map((g) => (
            <span key={g} className="reg-sdg" data-sdg={g} title={`SDG ${g}: ${SDG_NAME[g] ?? ""}`}>{g}</span>
          ))}
        </span>
        {matched.length > 0 && (
          <span className="reg-row-line">
            <span className="reg-row-label">In {f.theme}:</span>
            <span>{matched.slice(0, SHOW).join(" · ")}</span>
            <More n={matched.length - SHOW} />
          </span>
        )}
        {serves.length > 0 && (
          <span className="reg-row-line">
            <span className="reg-row-label">Serves</span>
            {serves.slice(0, SHOW).map((p) => (
              <span key={p} className="reg-tag" data-tone="population" data-active={p === f.population || undefined}>{p}</span>
            ))}
            <More n={serves.length - SHOW} />
          </span>
        )}
        <span className="muted reg-row-signal">{signal(r)}</span>
      </span>
    </Link>
  );
}

export function RegistryClient({ rows, initialType }: { rows: RegistryRow[]; initialType: Filters["kind"] }) {
  const [f, setF] = useState<Filters>({ kind: initialType, ...DEFAULTS });
  const set = (patch: Partial<Filters>) => setF((prev) => ({ ...prev, ...patch }));

  const counts = {
    all: rows.length,
    org: rows.filter((r) => r.kind === "org").length,
    funder: rows.filter((r) => r.kind === "funder").length,
  };
  const inBucket = f.kind === "all" ? rows : rows.filter((r) => r.kind === f.kind);

  const options = useMemo(() => {
    const domains = present(rows.flatMap((r) => [...new Set(r.themes.map((t) => t.domain).filter((d): d is string => !!d))]));
    const populations = present(rows.flatMap((r) => r.populations));
    const sdgs = [...new Set(rows.flatMap((r) => r.sdgs))].sort((a, b) => Number(a) - Number(b));
    const states = new Set(rows.flatMap((r) => r.states));
    const types = present(rows.filter((r) => r.kind === "funder" && r.funder_type).map((r) => r.funder_type!));
    return {
      domains, populations, sdgs, types,
      ne: NORTH_EAST.filter((s) => states.has(s)),
      open: rows.some((r) => r.open_call),
      invites: rows.some((r) => r.intake_mode === "invitation_only"),
    };
  }, [rows]);

  const filters: Filter[] = [
    {
      key: "theme", label: "Theme", value: f.theme, defaultValue: "all", onChange: (v) => set({ theme: v }),
      options: [["all", "All themes"], ...options.domains.map((d): [string, string] => [d, d])],
    },
    {
      key: "population", label: "Who they serve", value: f.population, defaultValue: "all", onChange: (v) => set({ population: v }),
      options: [["all", "Anyone served"], ...options.populations.map((p): [string, string] => [p, p])],
    },
    {
      key: "sdg", label: "SDG", value: f.sdg, defaultValue: "all", onChange: (v) => set({ sdg: v }),
      options: [["all", "All SDGs"], ...options.sdgs.map((g): [string, string] => [g, `SDG ${g}: ${SDG_NAME[g] ?? ""}`.replace(/: $/, "")])],
    },
    {
      key: "where", label: "Works in", value: f.where, defaultValue: "any", onChange: (v) => set({ where: v }),
      options: [
        ["any", "Anywhere"], ["ne", "North East, all 8 states"],
        ...options.ne.map((s): [string, string] => [s, s]), ["out", "Outside the North East"],
      ],
    },
  ];
  if (f.kind === "org") {
    filters.push({
      key: "reg", label: "Registrations", value: f.reg, defaultValue: "any", onChange: (v) => set({ reg: v }),
      options: [["any", "Any registrations"], ["csr1", "CSR-1 on file"], ["12a80g", "12A and 80G on file"], ["fcra", "FCRA registered"]],
    });
  }
  if (f.kind === "funder") {
    filters.push({
      key: "ftype", label: "Funder type", value: f.ftype, defaultValue: "all", onChange: (v) => set({ ftype: v }),
      options: [["all", "All funder types"], ...options.types.map((t): [string, string] => [t, funderTypeLabel(t)])],
    });
    if (options.open || options.invites) {
      filters.push({
        key: "approach", label: "How to approach", value: f.approach, defaultValue: "any",
        onChange: (v) => set({ approach: v }),
        options: [
          ["any", "Any approach"],
          ...(options.open ? [["open", "Open call now"] as [string, string]] : []),
          ...(options.invites ? [["invites", "Invites partners"] as [string, string]] : []),
        ],
      });
    }
  }

  const shown = rows.filter((r) => matches(r, f));
  const anySet = (Object.keys(DEFAULTS) as (keyof typeof DEFAULTS)[]).some((k) => f[k] !== DEFAULTS[k]);
  const resetKey = JSON.stringify(f);
  const [n, more] = useShowMore(resetKey, PAGE);
  const visible = shown.slice(0, n);

  return (
    <div className="reg">
      <header className="reg-head">
        <h1>Registry</h1>
        <p className="muted reg-lede">
          Civil-society organisations and funders working in India&apos;s North East, each with the sources behind it.
        </p>
      </header>

      <BucketCards
        items={[
          { key: "all", label: "All", count: counts.all, sub: SUB.all },
          { key: "org", label: "CSOs", count: counts.org, sub: SUB.org },
          { key: "funder", label: "Funders", count: counts.funder, sub: SUB.funder },
        ]}
        active={f.kind}
        onPick={(kind) => set({ kind, reg: "any", ftype: "all", approach: "any" })}
      />
      <FilterRow filters={filters} />
      <SearchBox value={f.q} onChange={(q) => set({ q })} placeholder="Search names, districts, programmes and funders…" />

      <div className="reg-count">
        <span className="muted">{anySet ? `${shown.length} match` : `${inBucket.length} in the Registry`}</span>
        {anySet && (
          <button type="button" className="reg-clear" onClick={() => set(DEFAULTS)}>Clear filters ✕</button>
        )}
      </div>

      <div className="reg-list">
        {visible.map((r) => <Row key={`${r.kind}-${r.id}`} r={r} f={f} />)}
        {shown.length === 0 && <div className="muted reg-none">No entries match these filters.</div>}
        <ListMore shown={visible.length} total={shown.length} onMore={more} page={PAGE} />
        {shown.length > 0 && (
          <div className="muted reg-shown" aria-live="polite">{visible.length} of {shown.length} shown</div>
        )}
      </div>
    </div>
  );
}
