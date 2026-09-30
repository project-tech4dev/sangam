"use client";

import { useState } from "react";
import { EntityMark, ProgressBar } from "@/components/ui";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { ScoreRow } from "@/lib/api";

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
  const tone = pct >= 65 ? "var(--color-accent-2-700)" : "var(--color-accent-600)";
  const toneText = pct >= 65 ? "text-sage-700" : "text-terracotta-600";

  async function toggle() {
    if (!open && !detail) {
      setLoading(true);
      try {
        const res = await fetch(`${API}/api/scores/${score.id}`, {
          headers: { Authorization: "Bearer dev" },
        });
        if (res.ok) setDetail(await res.json());
      } finally {
        setLoading(false);
      }
    }
    setOpen(!open);
  }

  return (
    <Card className="gap-3">
      <CardHeader className="flex flex-wrap items-center gap-3.5">
        <EntityMark name={headline} size={40} />
        <div className="min-w-50 flex-1">
          <CardTitle className="text-base font-bold">{headline}</CardTitle>
          <CardDescription className="text-xs">
            Rubric {score.rubric_version} · {score.scored_by} ·{" "}
            {new Date(score.scored_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
          </CardDescription>
        </div>
        <div className="text-right">
          <span className={`text-2xl font-bold ${toneText}`}>
            {score.total_score}
          </span>
          <span className="text-sm text-muted-foreground"> / {score.max_score}</span>
        </div>
      </CardHeader>
      <CardContent className="gap-2.5">
        <ProgressBar pct={pct} color={tone} />
        {score.notes && <p className="m-0 text-xs text-muted-foreground">{score.notes}</p>}
        <Button variant="ghost" size="sm" className="self-start px-0 hover:bg-transparent hover:underline" onClick={toggle}>
          {open ? "Hide reasoning" : loading ? "Loading…" : "Why this score"}
        </Button>
        {open && detail && (
          <div className="flex flex-col gap-2.5">
            {detail.items.map((item) => (
              <div
                key={item.code}
                className="grid grid-cols-[minmax(140px,1fr)_2fr_auto] gap-3 border-t pt-2 text-xs"
              >
                <strong>{item.code}. {item.label}</strong>
                <span className="text-muted-foreground">{item.justification ?? "—"}</span>
                <span className="font-bold whitespace-nowrap">+{item.score} / {item.points}</span>
              </div>
            ))}
            {detail.adjustments.length > 0 && (
              <div className="flex flex-col gap-1.5 rounded-lg bg-accent p-3.5 text-xs text-terracotta-900">
                <div className="text-xs font-bold tracking-widest uppercase">Hand-vetting adjustments</div>
                {detail.adjustments.map((adj, i) => (
                  <div key={i}>
                    Criterion {adj.code}: {adj.old_score} → {adj.new_score} — {adj.reason}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
