"use client";

import { useState } from "react";
import { EntityMark, ProgressBar } from "@/components/ui";
import type { ScoreRow } from "@/lib/api";
import { authHeaders } from "@/lib/api/auth-headers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

type ScoreDetail = ScoreRow & {
  items: { code: string; label: string; points: number; score: number; justification: string | null }[];
  adjustments: { code: string | null; old_score: number | null; new_score: number | null; reason: string }[];
};

export function ScoreCard({ score, headline }: { score: ScoreRow; headline: string }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<ScoreDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const pct = Math.round((score.total_score / score.max_score) * 100);
  const tone = pct >= 65 ? "var(--color-accent-2-700)" : "var(--color-accent-750)";

  async function toggle() {
    if (!open && !detail) {
      setLoading(true);
      try {
        const res = await fetch(`${API}/api/scores/${score.id}`, { headers: await authHeaders() });
        if (res.ok) setDetail(await res.json());
      } finally {
        setLoading(false);
      }
    }
    setOpen(!open);
  }

  return (
    <article className="card elev-sm">
      <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
        <EntityMark name={headline} size={40} />
        <div style={{ flex: 1, minWidth: 200 }}>
          <div className="card-title">{headline}</div>
          <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>
            Rubric {score.rubric_version} · {score.scored_by} ·{" "}
            {new Date(score.scored_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <span style={{ fontFamily: "var(--font-heading)", fontSize: "var(--fs-xl)", fontWeight: 700, color: tone }}>
            {score.total_score}
          </span>
          <span className="muted" style={{ fontSize: "var(--fs-sm)" }}> / {score.max_score}</span>
        </div>
      </div>
      <ProgressBar pct={pct} color={tone} />
      {score.notes && <div className="card-body" style={{ fontSize: "var(--fs-xs)" }}>{score.notes}</div>}
      <button className="btn btn-ghost" style={{ alignSelf: "flex-start", padding: "4px 0" }} onClick={toggle}>
        {open ? "Hide reasoning" : loading ? "Loading…" : "Why this score"}
      </button>
      {open && detail && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {detail.items.map((item) => (
            <div
              key={item.code}
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(140px, 1fr) 2fr auto",
                gap: 12,
                fontSize: "var(--fs-xs)",
                borderTop: "1px solid var(--color-divider)",
                paddingTop: 8,
              }}
            >
              <strong>{item.code}. {item.label}</strong>
              <span className="muted">{item.justification ?? "—"}</span>
              <span style={{ fontWeight: 700, whiteSpace: "nowrap" }}>+{item.score} / {item.points}</span>
            </div>
          ))}
          {detail.adjustments.length > 0 && (
            <div
              className="card"
              style={{ background: "var(--color-accent-100)", border: "none", padding: 14, gap: 6 }}
            >
              <div className="card-kicker" style={{ color: "var(--color-accent-900)" }}>
                Vetting adjustments
              </div>
              {detail.adjustments.map((adj, i) => (
                <div key={i} style={{ fontSize: "var(--fs-xs)", color: "var(--color-accent-900)" }}>
                  Criterion {adj.code}: {adj.old_score} → {adj.new_score} — {adj.reason}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </article>
  );
}
