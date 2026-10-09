"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { EntityMark } from "@/components/ui/primitives";
import { authHeaders } from "@/lib/api/auth-headers";
import { addedOf, completeness, isSaved, profileOf, topicBar, topicLine } from "../lib/done";
import type { QueueItem, ResearchCoverage } from "../lib/types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";
const CELLS = 20;

async function get<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API}${path}`, { headers: await authHeaders() });
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

const pct = (share: number) => `${Math.round(share * 100)}%`;
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** One block per topic fact: what Sangam had, what this save added, then empty up to the widest topic. */
function TopicCells({ kept, added, width }: { kept: number; added: number; width: number }) {
  return (
    <span className="done-cells done-cells-topic" aria-hidden>
      {Array.from({ length: width }, (_, i) => (
        <span key={i} className="done-cell" data-part={i < kept ? "kept" : i < kept + added ? "added" : "none"} />
      ))}
    </span>
  );
}

function SavedRow({ c }: { c: ResearchCoverage }) {
  const [open, setOpen] = useState(false);
  const share = completeness(c);
  const had = Math.round(share.before * CELLS);
  const now = Math.round(share.after * CELLS);
  const href = profileOf(c);
  const width = Math.max(1, ...c.concepts.map((t) => {
    const b = topicBar(t);
    return b.kept + b.updated + b.added;
  }));
  return (
    <li className="done-row">
      <button type="button" className="done-row-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="done-row-name">
          <EntityMark name={c.name} size={28} />
          <strong>{c.name}</strong>
        </span>
        <span className="done-cells" aria-label={`Profile ${pct(share.before)} complete before, ${pct(share.after)} after`}>
          {Array.from({ length: CELLS }, (_, i) => (
            <span key={i} className="done-cell" data-part={i < had ? "kept" : i < now ? "added" : "empty"} />
          ))}
        </span>
        <span className="done-row-numbers">
          <span className="done-row-pct">
            <span>
              <span className="done-before">{pct(share.before)}</span> → <strong>{pct(share.after)}</strong>
            </span>
            <span className="done-row-facts">+{plural(addedOf(c), "fact")}</span>
          </span>
          <span className="done-row-toggle">{open ? "Hide ▴" : "Show ▾"}</span>
        </span>
      </button>
      {open && (
        <div className="done-row-detail">
          <div role="list" aria-label="By topic" className="done-topics">
            {c.concepts.map((t) => {
              const b = topicBar(t);
              return (
                <div role="listitem" key={t.concept} className="done-topic">
                  <span>{t.title}</span>
                  <TopicCells kept={b.kept + b.updated} added={b.added} width={width} />
                  <span className="done-topic-line">{topicLine(t)}</span>
                </div>
              );
            })}
          </div>
          {href && (
            <div className="done-actions">
              <Link href={href} className="btn btn-secondary">
                Open profile →
              </Link>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

/** The Done step: how much more complete each saved profile is, from the coverage endpoint. */
export function DoneReport({
  slugs,
  since,
  onStartOver,
  fallback,
}: {
  slugs: string[];
  /** When the run began, so only names it queued are shown. */
  since: number | null;
  onStartOver: () => void;
  /** Shown until the numbers arrive, and instead of them when none come back. */
  fallback: ReactNode;
}) {
  const [all, setAll] = useState<ResearchCoverage[] | null>(null);
  const [queued, setQueued] = useState<QueueItem[]>([]);
  const key = slugs.join("|");

  useEffect(() => {
    let cancelled = false;
    // Between a pause's answer and the resume the run looks finished for a moment; don't dry-run every save for that.
    const wait = setTimeout(async () => {
      const [found, queue] = await Promise.all([
        Promise.all(key.split("|").map((slug) => get<ResearchCoverage>(`/api/ingest/research/${encodeURIComponent(slug)}/coverage`))),
        get<QueueItem[]>("/api/ingest/queue?limit=50"),
      ]);
      if (cancelled) return;
      setAll(found.filter((c): c is ResearchCoverage => c !== null));
      setQueued((queue ?? []).filter((q) => since !== null && Date.parse(q.created_at) >= since));
    }, 500);
    return () => {
      cancelled = true;
      clearTimeout(wait);
    };
  }, [key, since]);

  if (all === null || all.length === 0) return <>{fallback}</>;

  const saved = all.filter(isSaved);
  const notSaved = all.filter((c) => !isSaved(c));
  const shares = saved.map(completeness);
  const avg = (pick: (s: { before: number; after: number }) => number) =>
    shares.reduce((n, s) => n + pick(s), 0) / Math.max(1, shares.length);
  const added = saved.reduce((n, c) => n + addedOf(c), 0);
  const title = saved.length > 0 ? `Saved ${plural(saved.length, "organisation")}` : "Nothing was saved";
  const sub =
    saved.length === 0
      ? "What Sangam found is kept under Researched recently, so you can save it later."
      : `${saved.length === 1 ? "The profile is" : "Their profiles are"} now ${pct(avg((s) => s.after))} complete${
          saved.length === 1 ? "" : " on average"
        }, up from ${pct(avg((s) => s.before))}. ${plural(added, "new fact")} added, each linked to its proof.`;

  return (
    <section className="done" aria-label="Done">
      <div className="import-head">
        <h1 className="import-h1">{title}</h1>
        <p className="import-sub">{sub}</p>
      </div>

      <div className="done-table">
        {saved.length > 0 && (
          <>
            <div className="done-legend" aria-hidden>
              <span data-part="kept">Already in Sangam</span>
              <span data-part="added">Added now</span>
              <span className="done-legend-end">Profile complete</span>
            </div>
            <ul className="done-rows">
              {saved.map((c) => (
                <SavedRow key={c.slug} c={c} />
              ))}
            </ul>
          </>
        )}
        {notSaved.length > 0 && (
          <p className="done-unsaved">
            Not saved: {notSaved.map((c) => c.name).join(", ")}. What Sangam found is kept under Researched recently.
          </p>
        )}
      </div>

      {queued.length > 0 && (
        <div className="done-queued">
          <span className="card-kicker">{queued.length === 1 ? "One name needs a person" : `${queued.length} names need a person`}</span>
          {queued.map((q) => (
            <strong key={q.id}>
              {q.candidates[0]
                ? `Is “${q.raw_name}” the same as “${q.candidates[0].name}”?`
                : `Sangam couldn't place “${q.raw_name}”.`}
            </strong>
          ))}
          <span className="done-queued-note">Answer these on the Import page under Waiting for you.</span>
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
