"use client";

import { useState } from "react";
import { Check, CircleAlert } from "lucide-react";
import { EntityMark, Tag } from "@/components/ui";
import type { MatchDetail, MatchRow, MatchTier } from "@/lib/api";
import { getDetail } from "./api";
import { funderTypeLabel } from "./funderType";

export const TIER_LABEL: Record<MatchTier, string> = {
  strong: "Strong fit",
  medium: "Medium fit",
  weak: "Weak fit",
  not_scored: "Not scored",
};
const TIER_TONE = { strong: "accent-2", medium: "accent", weak: "neutral", not_scored: "outline" } as const;

export const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

function Delta({ now, before }: { now: number | null; before: number | null }) {
  if (now === null || before === null || now === before) return null;
  const up = now > before;
  return (
    <span className="fm-delta" data-up={up}>
      {up ? "▲" : "▼"} {Math.abs(now - before)} since the last run
    </span>
  );
}

export function MatchCard({ match, rank }: { match: MatchRow; rank: number }) {
  const [detail, setDetail] = useState<MatchDetail | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  function onToggle(event: React.SyntheticEvent<HTMLDetailsElement>) {
    if (!event.currentTarget.open || detail) return;
    getDetail(match.id).then(setDetail, (error: Error) => setProblem(error.message));
  }

  return (
    <article className="fm-card" aria-label={match.funder.name}>
      <div className="fm-card-top">
        <span className="fm-rank">#{rank}</span>
        <EntityMark name={match.funder.name} size={40} />
        <div className="fm-name">
          <h3 className="card-title">{match.funder.name}</h3>
          <span className="muted fm-meta">{funderTypeLabel(match.funder.funder_type)}</span>
        </div>
        <div className="fm-score">
          <span className="fm-score-num">
            {match.score ?? "—"}
            <small> / 100</small>
          </span>
          <span className="fm-bar" aria-hidden>
            <span className="fm-bar-fill" data-tier={match.tier} style={{ width: `${match.score ?? 0}%` }} />
          </span>
          <Tag tone={TIER_TONE[match.tier]}>{TIER_LABEL[match.tier]}</Tag>
          <Delta now={match.score} before={match.prev_score} />
        </div>
      </div>

      <ul className="fm-why">
        {match.card.reasons.map((reason) => (
          <li key={reason.criterion + reason.text} data-kind={reason.kind}>
            {reason.kind === "fit" ? <Check className="icon icon-sm" /> : <CircleAlert className="icon icon-sm" />}
            <span>{reason.text}</span>
          </li>
        ))}
      </ul>

      <details className="import-disclosure fm-reason" onToggle={onToggle}>
        <summary className="btn-ghost">Why this score</summary>
        {problem ? (
          <p className="import-error">{problem}</p>
        ) : !detail ? (
          <p className="muted">Loading…</p>
        ) : (
          <div className="fm-reason-body">
            <div>
              <h4 className="eyebrow">In short</h4>
              <p>{detail.detail.summary}</p>
            </div>
            {detail.detail.criteria.length > 0 && (
              <div>
                <h4 className="eyebrow">Criterion by criterion</h4>
                <div className="fm-crit">
                  {detail.detail.criteria.map((c) => (
                    <div key={c.code} className="fm-crit-row">
                      <div className="fm-crit-name">
                        <strong>{c.label}</strong>
                        <span className="muted">
                          {c.note} {c.cites.join(" ")}
                        </span>
                      </div>
                      <div className="fm-crit-pts">{c.points === null ? <span className="muted">unknown</span> : `${c.points} / ${c.max}`}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {detail.detail.not_judged.length > 0 && (
              <div>
                <h4 className="eyebrow">Not judged</h4>
                <p className="muted">{detail.detail.not_judged.join(" ")}</p>
              </div>
            )}
            {detail.detail.improve.length > 0 && (
              <div className="fm-improve">
                <h4 className="eyebrow">What would raise the score</h4>
                <ul>
                  {detail.detail.improve.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            )}
            <p className="muted fm-meta">
              From the run of {shortDate(detail.run_at)} · rubric {detail.rubric_version} · every criterion cites the record it rests on
            </p>
          </div>
        )}
      </details>
    </article>
  );
}
