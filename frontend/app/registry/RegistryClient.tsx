"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { EntityMark, StatusChip, Tag } from "../components/ui";
import type { RegistryEntry } from "../lib/api";

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
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <header style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div className="eyebrow">The Registry</div>
        <h1 style={{ fontSize: 30 }}>Every organisation and funder in the base</h1>
        <p className="muted" style={{ margin: 0, maxWidth: 640 }}>
          Hand-vetted profiles of North East India CSOs and the funders active around them. Every
          field traces to a source.
        </p>
      </header>

      <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
        <input
          className="input"
          style={{ maxWidth: 420 }}
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
        <span className="muted" style={{ marginLeft: "auto", fontSize: 12.5 }}>
          {shown.length} of {entries.length} entries
        </span>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {places.map((p) => (
          <button key={p} className="pill" data-active={place === p} onClick={() => setPlace(p)}>
            {p}
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <div className="card" style={{ alignItems: "center", padding: 40 }}>
          <div className="card-title">Nothing matches</div>
          <div className="card-body">Try a different search, or clear the filters.</div>
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
            gap: 18,
          }}
        >
          {shown.map((entry) => (
            <article key={`${entry.kind}-${entry.id}`} className="card elev-sm">
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <EntityMark name={entry.name} />
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <Tag tone="neutral">{entry.kind}</Tag>
                  <StatusChip status={entry.status} />
                </div>
              </div>
              <div className="card-title" style={{ fontSize: 19 }}>{entry.name}</div>
              <div className="muted" style={{ fontSize: 12.5 }}>{entry.where}</div>
              {entry.blurb && <div className="card-body">{entry.blurb}</div>}
              {entry.tags.length > 0 && (
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {entry.tags.map((tag) => (
                    <Tag key={tag} tone="accent-2">{tag}</Tag>
                  ))}
                </div>
              )}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginTop: "auto",
                  paddingTop: 8,
                  gap: 10,
                }}
              >
                <span className="muted-2" style={{ fontSize: 11.5 }}>{entry.meta}</span>
                <Link href={entry.href} className="btn btn-secondary" style={{ padding: "6px 14px", fontSize: 12 }}>
                  Open profile →
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}

      {vetting > 0 && (
        <div className="card" style={{ background: "var(--color-accent-2-100)", border: "none" }}>
          <div className="card-body" style={{ color: "var(--color-accent-2-900)" }}>
            {vetting} of {entries.length} entries are still in vetting — their profiles show exactly
            what has and hasn&apos;t been verified yet.
          </div>
        </div>
      )}
    </div>
  );
}
