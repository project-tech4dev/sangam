"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { EntityMark, StatusChip, Tag } from "@/components/ui";
import type { RegistryEntry } from "@/features/registry/entries";

export function RegistryClient({
  entries,
  initialType,
}: {
  entries: RegistryEntry[];
  initialType: "all" | "CSO" | "Funder";
}) {
  const [q, setQ] = useState("");
  const [type, setType] = useState<"all" | "CSO" | "Funder">(initialType);
  const [place, setPlace] = useState("All places");

  const places = useMemo(
    () => ["All places", ...Array.from(new Set(entries.flatMap((e) => e.states))).sort()],
    [entries],
  );

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return entries.filter((entry) => {
      if (type !== "all" && entry.kind !== type) return false;
      if (place !== "All places" && !entry.states.includes(place)) return false;
      if (!needle) return true;
      const haystack = `${entry.name} ${entry.where} ${entry.blurb ?? ""} ${entry.tags.join(" ")} ${entry.kind}`.toLowerCase();
      return haystack.includes(needle);
    });
  }, [entries, q, type, place]);

  const vetting = entries.filter((e) => e.status === "partial").length;

  return (
    <div className="reg">
      <header className="reg-head">
        <div className="eyebrow">The Registry</div>
        <h1>Every organisation and funder in the base</h1>
        <p className="muted reg-lede">
          Vetted profiles of North East India CSOs and the funders active around them. Every
          field traces to a source.
        </p>
      </header>

      <div className="reg-controls">
        <input
          className="input"
          placeholder="Search organisations, funders, districts, sectors…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <div className="seg" role="tablist">
          {(["all", "CSO", "Funder"] as const).map((option) => (
            <button
              key={option}
              className="seg-opt"
              data-active={type === option}
              onClick={() => setType(option)}
            >
              {option === "all" ? "All" : option === "CSO" ? "CSOs" : "Funders"}
            </button>
          ))}
        </div>
        <span className="muted reg-count">
          {shown.length} of {entries.length} entries
        </span>
      </div>

      <div className="reg-places">
        {places.map((p) => (
          <button key={p} className="pill" data-active={place === p} onClick={() => setPlace(p)}>
            {p}
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <div className="card reg-empty">
          <div className="card-title">Nothing matches</div>
          <div className="card-body">Try a different search, or clear the filters.</div>
        </div>
      ) : (
        <div className="reg-grid">
          {shown.map((entry) => (
            <article key={`${entry.kind}-${entry.id}`} className="card elev-sm reg-card">
              <div className="reg-card-top">
                <EntityMark name={entry.name} />
                <div className="reg-chips">
                  <Tag tone="neutral">{entry.kind}</Tag>
                  <StatusChip status={entry.status} />
                </div>
              </div>
              <div className="card-title">{entry.name}</div>
              <div className="muted reg-where">{entry.where}</div>
              {entry.blurb && <div className="card-body">{entry.blurb}</div>}
              {entry.tags.length > 0 && (
                <div className="reg-chips">
                  {entry.tags.map((tag) => (
                    <Tag key={tag} tone="accent-2">{tag}</Tag>
                  ))}
                </div>
              )}
              <div className="reg-foot">
                <span className="muted-2">{entry.meta}</span>
                <Link href={entry.href} className="btn btn-secondary">
                  Open profile →
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}

      {vetting > 0 && (
        <div className="card reg-vetting">
          <div className="card-body">
            {vetting} of {entries.length} entries are still in vetting — their profiles show exactly
            what has and hasn&apos;t been verified yet.
          </div>
        </div>
      )}
    </div>
  );
}
