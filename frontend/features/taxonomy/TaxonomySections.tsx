"use client";

import { useState } from "react";
import { Tag } from "@/components/ui";
import { COMMON, LENSES, SDG_LABEL, scheduleViiInUse } from "./data";
import type { Domain, SubTheme, Theme } from "./types";

/** Section ids, shared with the page's section index. */
export const SHARED_ID = "shared-vocabulary";

/** One domain's themes as a section of the Taxonomy tab, anchored at #<domain>. */
export function DomainSection({ domain }: { domain: Domain }) {
  const [open, setOpen] = useState<Record<string, boolean>>({ [domain.themes[0]?.code ?? ""]: true });
  const subThemes = domain.themes.reduce((n, t) => n + t.sub_themes.length, 0);
  return (
    <section id={domain.domain} className="flex scroll-mt-24 flex-col gap-4">
      <h3 style={{ fontSize: "var(--fs-lg)" }}>{domain.label}</h3>
      <p className="muted measure m-0">
        {domain.themes.length > 0 && `${domain.themes.length} themes, ${subThemes} sub-themes. `}
        {domain.source}.
      </p>
      {domain.themes.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {domain.themes.map((theme) => (
            <ThemeCard
              key={theme.code}
              theme={theme}
              open={open[theme.code] ?? false}
              onToggle={() => setOpen({ ...open, [theme.code]: !open[theme.code] })}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ThemeCard({ theme, open, onToggle }: { theme: Theme; open: boolean; onToggle: () => void }) {
  return (
    <div className="card" style={{ gap: 16 }}>
      <button
        onClick={onToggle}
        aria-expanded={open}
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          width: "100%",
          padding: 0,
          border: "none",
          background: "none",
          cursor: "pointer",
          textAlign: "left",
          fontFamily: "var(--font-heading)",
          fontSize: "var(--fs-md)",
          fontWeight: 600,
          color: "var(--color-text)",
        }}
      >
        <span>{theme.label}</span>
        <span className="muted-2" style={{ marginLeft: "auto", fontSize: "var(--fs-xs)", fontWeight: 400, whiteSpace: "nowrap" }}>
          {theme.sub_themes.length} sub-themes
        </span>
        <span className="muted-2" style={{ width: 12, textAlign: "center" }}>{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {theme.sub_themes.map((s) => (
            <SubThemeRow key={s.code} subTheme={s} />
          ))}
        </div>
      )}
    </div>
  );
}

/** One sub-theme: its name, the SDGs it reports against, then its CSR and scheme crosswalks. */
function SubThemeRow({ subTheme }: { subTheme: SubTheme }) {
  const facts: [string, string][] = [
    ["Schedule VII", subTheme.csr.map((c) => `(${c.clause}) ${c.sector}`).join(" · ")],
    ...(subTheme.schemes.length ? [["Schemes", subTheme.schemes.join(" · ")] as [string, string]] : []),
  ];
  return (
    <div
      style={{
        background: "var(--color-bg)",
        borderRadius: "var(--radius-row)",
        padding: "16px 18px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div style={{ fontWeight: 600 }}>{subTheme.label}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {subTheme.sdgs.map((n) => (
          <Tag key={n} tone="accent-2">SDG {n} · {SDG_LABEL.get(n) ?? ""}</Tag>
        ))}
      </div>
      <dl
        style={{
          margin: 0,
          display: "grid",
          gridTemplateColumns: "max-content minmax(0, 1fr)",
          gap: "6px 16px",
          fontSize: "var(--fs-xs)",
        }}
      >
        {facts.map(([label, value]) => (
          <div key={label} style={{ display: "contents" }}>
            <dt className="muted-2" style={{ fontWeight: 600 }}>{label}</dt>
            <dd className="muted" style={{ margin: 0 }}>{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** The vocabularies every domain shares, anchored at #shared-vocabulary. */
export function SharedSection() {
  return (
    <section id={SHARED_ID} className="flex scroll-mt-24 flex-col gap-4">
      <h3 style={{ fontSize: "var(--fs-lg)" }}>Shared vocabulary</h3>
      <p className="muted measure m-0">
        These apply across every domain. Lenses are tagged alongside a sub-theme, and some add an SDG.
      </p>
      <VocabCard title={`Lenses (${LENSES.length})`}>
        {LENSES.map((l) => (
          <Tag key={l.code} tone="accent">
            {l.label}
            {l.adds_sdgs.length ? ` · adds SDG ${l.adds_sdgs.join(", ")}` : ""}
          </Tag>
        ))}
      </VocabCard>
      <VocabCard title={`Population groups (${COMMON.population.length})`}>
        {COMMON.population.map(([slug, label]) => (
          <Tag key={slug} tone="neutral">{label}</Tag>
        ))}
      </VocabCard>
      <VocabCard title={`SDGs (${COMMON.sdgs.length})`}>
        {COMMON.sdgs.map(([n, label]) => (
          <Tag key={n} tone="accent-2">SDG {n} · {label}</Tag>
        ))}
      </VocabCard>
      <div className="card" style={{ gap: 10 }}>
        <div className="card-kicker">Schedule VII in use</div>
        <div className="card-body measure">
          The Companies Act clauses and MCA sectors the sub-themes file under — the categories CSR
          filings report against.
        </div>
        <dl
          style={{
            margin: 0,
            display: "grid",
            gridTemplateColumns: "max-content minmax(0, 1fr)",
            gap: "8px 16px",
          }}
        >
          {scheduleViiInUse().map(({ clause, sectors }) => (
            <div key={clause} style={{ display: "contents" }}>
              <dt style={{ fontWeight: 600 }}>({clause})</dt>
              <dd style={{ margin: 0, display: "flex", flexWrap: "wrap", gap: 6 }}>
                {sectors.map((s) => (
                  <Tag key={s} tone="outline">{s}</Tag>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

function VocabCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card" style={{ gap: 10 }}>
      <div className="card-kicker">{title}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>{children}</div>
    </div>
  );
}
