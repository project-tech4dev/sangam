import type { ReactNode } from "react";
import { EntityMark } from "./primitives";

const HERO_BG: Record<string, string> = {
  "org-full": "var(--color-accent-2-800)",
  "org-partial": "var(--color-accent-800)",
  funder: "var(--color-accent-2-900)",
};

export function Hero({
  kind,
  kicker,
  name,
  blurb,
  chips,
  cta,
}: {
  kind: "org-full" | "org-partial" | "funder";
  kicker?: string;
  name: string;
  blurb?: string | null;
  chips?: ReactNode;
  cta?: ReactNode;
}) {
  return (
    <section
      style={{
        background: HERO_BG[kind],
        color: "#fff",
        borderRadius: "calc(var(--radius-lg) * 1.15)",
        padding: "32px 34px",
        display: "flex",
        gap: 24,
        alignItems: "flex-start",
        flexWrap: "wrap",
      }}
    >
      <EntityMark name={name} size={64} />
      <div style={{ flex: 1, minWidth: 260, display: "flex", flexDirection: "column", gap: 10 }}>
        {kicker && (
          <div className="eyebrow" style={{ color: "rgba(255,255,255,0.75)" }}>
            {kicker}
          </div>
        )}
        <h1 style={{ fontSize: 28, color: "#fff" }}>{name}</h1>
        {blurb && (
          <p style={{ margin: 0, fontSize: 14, color: "rgba(255,255,255,0.85)", maxWidth: 640 }}>{blurb}</p>
        )}
        {chips && <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}>{chips}</div>}
      </div>
      {cta}
    </section>
  );
}
