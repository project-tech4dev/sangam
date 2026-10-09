"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EntityMark } from "@/components/ui/primitives";
import { authHeaders } from "@/lib/api/auth-headers";
import { emptyReason, isSaved, profileOf, runTotal, squareOf, summaryLine, topicBar } from "../lib/done";
import type { QueueItem, ResearchCoverage } from "../lib/types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";
// Above this many organisations the report opens as a matrix, one row each.
const MATRIX_FROM = 4;
const SQUARE_WORDS = { new: "New", updated: "Updated", kept: "Already in Sangam", empty: "Nothing yet" };

async function get<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API}${path}`, { headers: await authHeaders() });
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

function Bars({ c }: { c: ResearchCoverage }) {
  const widest = Math.max(1, ...c.concepts.map((t) => {
    const b = topicBar(t);
    return b.kept + b.updated + b.added;
  }));
  return (
    <ul className="done-bars">
      {c.concepts.map((t) => {
        const why = emptyReason(t);
        const b = topicBar(t);
        return (
          <li key={t.concept} className="done-bar-row">
            <span className="done-bar-topic">{t.title}</span>
            {why ? (
              <span className="done-bar-why">{why}</span>
            ) : (
              <span className="done-bar" aria-label={`${b.kept} already in Sangam, ${b.updated} updated, ${b.added} new`}>
                <span className="done-seg" data-part="kept" style={{ width: `${(b.kept / widest) * 100}%` }} />
                <span className="done-seg" data-part="updated" style={{ width: `${(b.updated / widest) * 100}%` }} />
                <span className="done-seg" data-part="added" style={{ width: `${(b.added / widest) * 100}%` }} />
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function Legend() {
  return (
    <div className="done-legend" aria-hidden>
      <span data-part="kept">Already in Sangam</span>
      <span data-part="updated">Updated</span>
      <span data-part="added">New</span>
    </div>
  );
}

function Facts({ c }: { c: ResearchCoverage }) {
  if (c.facts_before === null || c.facts_after === null) return null;
  return (
    <span className="done-facts">
      {c.facts_before} → {c.facts_after} facts
    </span>
  );
}

function Org({ c }: { c: ResearchCoverage }) {
  const saved = isSaved(c);
  const href = profileOf(c);
  return (
    <section className="done-org" data-saved={saved}>
      <div className="done-org-head">
        <EntityMark name={c.name} size={32} />
        <div className="done-org-name">
          <strong>{c.name}</strong>
          <span className="done-line">{summaryLine(c)}</span>
        </div>
        {saved && <Facts c={c} />}
        <span className={`tag ${saved ? "tag-accent-2" : "tag-neutral"}`}>{saved ? "Saved" : "Not saved"}</span>
        {href && (
          <Link href={href} className="import-link">
            Open profile
          </Link>
        )}
      </div>
      {c.concepts.length > 0 && <Bars c={c} />}
    </section>
  );
}

function MatrixRow({ c }: { c: ResearchCoverage }) {
  const [open, setOpen] = useState(false);
  const saved = isSaved(c);
  return (
    <li className="done-matrix-item" data-saved={saved}>
      <button type="button" className="done-matrix-row" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="done-matrix-name">
          <EntityMark name={c.name} size={24} />
          <strong>{c.name}</strong>
        </span>
        <span className="done-squares">
          {c.concepts.map((t) => {
            const sq = squareOf(t);
            const why = sq === "empty" ? emptyReason(t) : null;
            return <span key={t.concept} className="done-square" data-part={sq} title={`${t.title}: ${why ?? SQUARE_WORDS[sq]}`} />;
          })}
        </span>
        <span className={`tag ${saved ? "tag-accent-2" : "tag-neutral"}`}>{saved ? "Saved" : "Not saved"}</span>
      </button>
      {open && (
        <div className="done-matrix-detail">
          <Org c={c} />
        </div>
      )}
    </li>
  );
}

type Filter = "all" | "saved" | "unsaved";

/** The Done step: what each organisation's save did, per topic, from the coverage endpoint. */
export function DoneReport({
  slugs,
  since,
  onStartOver,
}: {
  slugs: string[];
  /** When the run began, so only names it queued are shown. */
  since: number | null;
  onStartOver: () => void;
}) {
  const [all, setAll] = useState<ResearchCoverage[] | null>(null);
  const [queued, setQueued] = useState<QueueItem[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const key = slugs.join("|");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [found, queue] = await Promise.all([
        Promise.all(key.split("|").map((slug) => get<ResearchCoverage>(`/api/ingest/research/${encodeURIComponent(slug)}/coverage`))),
        get<QueueItem[]>("/api/ingest/queue?limit=50"),
      ]);
      if (cancelled) return;
      setAll(found.filter((c): c is ResearchCoverage => c !== null));
      setQueued((queue ?? []).filter((q) => since !== null && Date.parse(q.created_at) >= since));
    })();
    return () => {
      cancelled = true;
    };
  }, [key, since]);

  if (all === null) return <span className="muted">Putting the report together…</span>;
  if (all.length === 0) return null;

  const saved = all.filter(isSaved);
  const notSaved = all.filter((c) => !isSaved(c));
  const total = runTotal(all);
  const matrix = all.length >= MATRIX_FROM;
  const shown = all.filter((c) => filter === "all" || (filter === "saved") === isSaved(c));

  return (
    <section className="card done-card" aria-label="Done">
      <div className="done-head">
        <span className="card-kicker">Done</span>
        <strong className="done-title">
          {saved.length} saved{notSaved.length > 0 && `, ${notSaved.length} not saved`}
        </strong>
        {matrix && total && (
          <span className="done-facts">
            {total.before} → {total.after} facts
          </span>
        )}
      </div>

      {matrix ? (
        <>
          <div className="seg done-filter">
            {(
              [
                ["all", `All ${all.length}`],
                ["saved", `Saved ${saved.length}`],
                ["unsaved", `Not saved ${notSaved.length}`],
              ] as const
            ).map(([value, label]) => (
              <button key={value} type="button" className="seg-opt" data-active={filter === value} onClick={() => setFilter(value)}>
                {label}
              </button>
            ))}
          </div>
          <ul className="done-matrix">
            {shown.map((c) => (
              <MatrixRow key={c.slug} c={c} />
            ))}
          </ul>
        </>
      ) : (
        all.map((c) => <Org key={c.slug} c={c} />)
      )}
      <Legend />

      {queued.length > 0 && (
        <div className="done-queued">
          <span className="review-label">Waiting for you</span>
          <ul>
            {queued.map((q) => (
              <li key={q.id}>
                {q.candidates[0]
                  ? `Is “${q.raw_name}” the same as “${q.candidates[0].name}”?`
                  : `Sangam couldn't place “${q.raw_name}”.`}
              </li>
            ))}
          </ul>
          <span className="review-note">Answer these on the Import page under Waiting for you.</span>
        </div>
      )}

      <div className="done-actions">
        <button type="button" className="btn btn-primary" onClick={onStartOver}>
          Research something else
        </button>
      </div>
    </section>
  );
}
