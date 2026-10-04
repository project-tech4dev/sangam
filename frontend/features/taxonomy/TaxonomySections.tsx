"use client";

import { useState } from "react";
import { Tag } from "@/components/ui";
import { COMMON, POPULATION_LABEL, SDG_LABEL, SECTOR_LABEL, humanize } from "./data";
import type { Area, Domain, Leaf } from "./types";

/** Section ids, shared with the page's "In this article" index. */
export const SHARED_ID = "shared-vocabulary";

/** One domain tree as a section of the Taxonomy tab, anchored at #<domain>. */
export function DomainSection({ domain }: { domain: Domain }) {
  return (
    <section id={domain.domain} className="flex scroll-mt-24 flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <h3 style={{ fontSize: "var(--fs-lg)" }}>{domain.label}</h3>
        <Tag tone="outline">v{domain.version}</Tag>
        {domain.status === "draft" ? <Tag tone="accent">Draft</Tag> : <Tag tone="accent-2">Active</Tag>}
      </div>
      <DomainView domain={domain} />
    </section>
  );
}

/** The cross-domain vocabularies as the last section, anchored at #shared-vocabulary. */
export function SharedSection() {
  return (
    <section id={SHARED_ID} className="flex scroll-mt-24 flex-col gap-4">
      <h3 style={{ fontSize: "var(--fs-lg)" }}>Shared vocabulary</h3>
      <SharedVocabulary />
    </section>
  );
}

function DomainView({ domain }: { domain: Domain }) {
  const [open, setOpen] = useState<Record<string, boolean>>({ [domain.nodes[0]?.code ?? ""]: true });
  const addLabel = new Map<string, string>([
    ...(domain.variants?.items.map((v) => [v.code, v.label] as [string, string]) ?? []),
    ...domain.modifiers.map((m) => [m.code, m.label] as [string, string]),
  ]);

  return (
    <div className="flex flex-col gap-5">
      <p className="muted measure">
        <strong>{domain.tree_name}</strong> — {domain.source}
      </p>

      <div className="flex flex-col gap-2.5">
        {domain.nodes.map((area) => (
          <AreaCard
            key={area.code}
            area={area}
            levels={domain.levels}
            addLabel={addLabel}
            open={open[area.code] ?? false}
            onToggle={() => setOpen({ ...open, [area.code]: !open[area.code] })}
          />
        ))}
      </div>

      <div className="grid gap-3.5 md:grid-cols-3">
        {domain.variants && (
          <div className="card" style={{ gap: 8 }}>
            <div className="card-kicker">{humanize(domain.variants.level)}s</div>
            <div className="flex flex-wrap gap-1.5">
              {domain.variants.items.map((v) => (
                <Tag key={v.code} tone="track">{v.label}</Tag>
              ))}
            </div>
            <div className="card-body">
              {domain.variants.note ??
                `Applies across every ${humanize(domain.variants.apply_to_level).toLowerCase()}.`}
            </div>
          </div>
        )}
        <div className="card" style={{ gap: 8 }}>
          <div className="card-kicker">Modifiers</div>
          <div className="flex flex-wrap gap-1.5">
            {domain.modifiers.map((m) => (
              <Tag key={m.code} tone="accent">{m.label}</Tag>
            ))}
          </div>
          <div className="card-body">Added to a programme on top of its area; some add SDGs.</div>
        </div>
        <div className="card" style={{ gap: 8 }}>
          <div className="card-kicker">Enabling work</div>
          <div className="flex flex-wrap gap-1.5">
            {domain.enabler_kinds.map((k) => (
              <Tag key={k} tone="neutral">{humanize(k)}</Tag>
            ))}
          </div>
          <div className="card-body">Work that makes programmes possible rather than delivering one.</div>
        </div>
      </div>

      {domain.notes && domain.notes.length > 0 && (
        <div className="card" style={{ background: "var(--color-accent-2-100)", border: "none", gap: 6 }}>
          <div className="card-kicker" style={{ color: "var(--color-accent-2-900)" }}>Notes</div>
          <ul className="card-body measure m-0 flex flex-col gap-1.5 pl-5" style={{ color: "var(--color-accent-2-900)" }}>
            {domain.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      )}

      <details className="card" style={{ gap: 10 }}>
        <summary className="cursor-pointer font-semibold">Sources ({domain.sources.length})</summary>
        <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
          {domain.sources.map((s) => (
            <li key={s.id} className="card-body">
              {s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer">{s.name}</a>
              ) : (
                <strong>{s.name}</strong>
              )}
              <span className="muted"> · {s.publisher} — used for {s.used_for}</span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function AreaCard({
  area,
  levels,
  addLabel,
  open,
  onToggle,
}: {
  area: Area;
  levels: string[];
  addLabel: Map<string, string>;
  open: boolean;
  onToggle: () => void;
}) {
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
        <span className="muted-2">{area.code}</span>
        <span>{area.label}</span>
        <span className="muted-2" style={{ marginLeft: "auto", fontSize: "var(--fs-xs)", fontWeight: 400, whiteSpace: "nowrap" }}>
          {area.children.length} {humanize(levels[1] ?? "item").toLowerCase()}s
        </span>
        <span className="muted-2" style={{ width: 12, textAlign: "center" }}>{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {area.note && <div className="card-body measure">{area.note}</div>}
          {area.children.map((leaf) => (
            <LeafRow key={leaf.code} areaCode={area.code} leaf={leaf} addLabel={addLabel} />
          ))}
        </div>
      )}
    </div>
  );
}

/** One sub-area: name, its tags, then its rules and references as labelled rows. */
function LeafRow({ areaCode, leaf, addLabel }: { areaCode: string; leaf: Leaf; addLabel: Map<string, string> }) {
  const adds = Object.entries(leaf.adds ?? {});
  const targets = leaf.refs.sdg_targets ?? [];
  const programmes = leaf.refs.india_programmes ?? [];
  const facts: [string, string][] = [
    ...(adds.length
      ? [["Also adds", adds.map(([code, sdgs]) => `${addLabel.get(code) ?? humanize(code)} → SDG ${sdgs.join(", ")}`).join(" · ")] as [string, string]]
      : []),
    ...(targets.length ? [["SDG targets", targets.join(", ")] as [string, string]] : []),
    ...(programmes.length ? [["Programmes", programmes.join(", ")] as [string, string]] : []),
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
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, fontWeight: 600 }}>
        <span className="muted-2" style={{ fontSize: "var(--fs-xs)" }}>{areaCode}.{leaf.code}</span>
        <span>{leaf.label}</span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {leaf.sdgs.map((n) => (
          <Tag key={`sdg-${n}`} tone="accent-2">SDG {n} · {SDG_LABEL.get(n) ?? ""}</Tag>
        ))}
        {leaf.sectors.map((slug) => (
          <Tag key={slug} tone="outline">{SECTOR_LABEL.get(slug) ?? slug}</Tag>
        ))}
      </div>
      {leaf.note && <div className="card-body measure">{leaf.note}</div>}
      {facts.length > 0 && (
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
      )}
    </div>
  );
}

function SharedVocabulary() {
  const resolve = (slug: string) => {
    if (slug.startsWith("sector-")) return SECTOR_LABEL.get(slug.slice(7)) ?? slug;
    if (slug.startsWith("pop-")) return POPULATION_LABEL.get(slug.slice(4)) ?? slug;
    return slug;
  };
  return (
    <div className="flex flex-col gap-5">
      <p className="muted measure">
        These apply to every domain: a programme in any tree carries its SDGs, a sector label and
        the population groups it serves.
      </p>
      <VocabCard title={`SDGs (${COMMON.sdgs.length})`}>
        {COMMON.sdgs.map(([n, label]) => (
          <Tag key={n} tone="accent-2">SDG {n} · {label}</Tag>
        ))}
      </VocabCard>
      <VocabCard title={`Sectors (${COMMON.sectors.length})`}>
        {COMMON.sectors.map(([slug, label]) => (
          <Tag key={slug} tone="outline">{label}</Tag>
        ))}
      </VocabCard>
      <VocabCard title={`Population groups (${COMMON.population.length})`}>
        {COMMON.population.map(([slug, label]) => (
          <Tag key={slug} tone="neutral">{label}</Tag>
        ))}
      </VocabCard>
      <div className="card" style={{ gap: 10 }}>
        <div className="card-kicker">From NGO Darpan</div>
        <div className="card-body measure">
          How the sector names organisations choose on NGO Darpan map onto Sangam&apos;s vocabulary.
        </div>
        <table className="w-full border-collapse text-sm">
          <tbody>
            {Object.entries(COMMON.darpan_map).map(([darpan, slugs]) => (
              <tr key={darpan} className="border-t border-(--color-divider)">
                <td className="py-2 pr-4 align-top font-semibold">{darpan}</td>
                <td className="py-2">
                  <div className="flex flex-wrap gap-1.5">
                    {slugs.map((slug) => (
                      <Tag key={slug} tone={slug.startsWith("pop-") ? "neutral" : "outline"}>{resolve(slug)}</Tag>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function VocabCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card" style={{ gap: 10 }}>
      <div className="card-kicker">{title}</div>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </div>
  );
}
