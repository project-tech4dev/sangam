"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { EntityMark } from "@/components/ui/primitives";
import { authHeaders } from "@/lib/api/auth-headers";
import { addedOf, completeness, gapDetail, isSaved, profileOf, topicBar, topicLine, wasFound } from "../lib/done";
import type { QueueItem, ResearchCoverage, ResearchReview } from "../lib/types";
import { Answer, Missing } from "./ReviewFields";
import { ScreenReview } from "./ScreenReview";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";
const CELLS = 20;
const SHOWN = 10;

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

/** Everything about one organisation: by topic, what was found with proof, what wasn't and why. */
function Report({ c, onReview }: { c: ResearchCoverage; onReview: () => void }) {
  const saved = isSaved(c);
  const [review, setReview] = useState<ResearchReview | null>(null);
  const [failed, setFailed] = useState(false);
  const [all, setAll] = useState(false);
  const href = profileOf(c);

  useEffect(() => {
    let cancelled = false;
    void get<ResearchReview>(`/api/ingest/research/${encodeURIComponent(c.slug)}/review`).then((body) => {
      if (cancelled) return;
      if (body) setReview(body);
      else setFailed(true);
    });
    return () => {
      cancelled = true;
    };
  }, [c.slug]);

  const width = Math.max(
    1,
    ...c.concepts.map((t) => {
      const b = topicBar(t);
      return b.kept + b.updated + b.added;
    }),
  );
  const reasons = new Map(c.concepts.map((t) => [t.concept, gapDetail(t)]));
  const held = c.concepts.filter((t) => t.held > 0);
  const found = review?.answers ?? [];

  return (
    <div className="done-row-detail">
      <section className="done-section">
        <span className="done-section-title">By topic</span>
        <div role="list" aria-label="By topic" className="done-topics">
          {c.concepts.map((t) => {
            const b = topicBar(t);
            return (
              <div role="listitem" key={t.concept} className="done-topic">
                <span>{t.title}</span>
                <TopicCells kept={saved ? b.kept + b.updated : (t.before ?? 0)} added={saved ? b.added : 0} width={width} />
                <span className="done-topic-line">
                  {saved ? topicLine(t) : (t.before ?? 0) > 0 ? "Already in Sangam" : "Nothing yet"}
                </span>
              </div>
            );
          })}
        </div>
      </section>

      {review === null && !failed && <span className="done-topic-line">Getting the answers…</span>}
      {failed && <span className="done-topic-line">Sangam couldn&apos;t load the answers.</span>}

      {found.length > 0 && (
        <section className="done-section">
          <span className="done-section-title">What Sangam found ({found.length})</span>
          <div>
            {(all ? found : found.slice(0, SHOWN)).map((a, i) => (
              <Answer key={`${a.concept}-${i}`} answer={a} />
            ))}
          </div>
          {found.length > SHOWN && (
            <button type="button" className="review-more" onClick={() => setAll(!all)}>
              {all ? "Show fewer" : `Show all ${found.length}`}
            </button>
          )}
        </section>
      )}

      {review && review.missing.length > 0 && (
        <section className="done-section">
          <span className="done-section-title">Not found, and why</span>
          <div>
            {review.missing.map((m) => (
              <Missing key={m.concept} m={m} reason={reasons.get(m.concept) ?? undefined} />
            ))}
          </div>
        </section>
      )}

      {held.length > 0 && (
        <section className="done-section">
          <span className="done-section-title">Held back</span>
          <ul className="done-held">
            {held.map((t) => (
              <li key={t.concept}>
                {t.title}: {plural(t.held, "fact")}
              </li>
            ))}
          </ul>
          <span className="done-topic-line">These stay in the research, because they couldn&apos;t be saved as they are.</span>
        </section>
      )}

      <div className="done-actions">
        {href && (
          <Link href={href} className="btn btn-secondary">
            Open profile →
          </Link>
        )}
        {!saved && (
          <button type="button" className="btn btn-primary" onClick={onReview}>
            Review &amp; save
          </button>
        )}
      </div>
    </div>
  );
}

function OrgRow({
  c,
  declined,
  onSaved,
  onDeclined,
}: {
  c: ResearchCoverage;
  declined: boolean;
  onSaved: () => void;
  onDeclined: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const saved = isSaved(c);
  const share = completeness(c);
  const had = Math.round(share.before * CELLS);
  const now = saved ? Math.round(share.after * CELLS) : had;
  const found = c.concepts.filter(wasFound).length;
  // Before a save an NGO has no dry run, so its bars would all be empty: say what was found instead.
  const bars = saved || share.before > 0;
  return (
    <li className="done-row" data-saved={saved}>
      <div className="done-row-line">
        <button type="button" className="done-row-head" aria-expanded={open} onClick={() => setOpen(!open)}>
          <span className="done-row-name">
            <EntityMark name={c.name} size={28} />
            <strong>{c.name}</strong>
          </span>
          {bars ? (
            <span
              className="done-cells"
              aria-label={
                saved
                  ? `Profile ${pct(share.before)} complete before, ${pct(share.after)} after`
                  : `Profile ${pct(share.before)} complete`
              }
            >
              {Array.from({ length: CELLS }, (_, i) => (
                <span key={i} className="done-cell" data-part={i < had ? "kept" : i < now ? "added" : "empty"} />
              ))}
            </span>
          ) : (
            <span className="done-row-found">
              Found answers on {found} of {c.concepts.length} topics
            </span>
          )}
          <span className="done-row-numbers">
            <span className="done-row-pct">
              {saved ? (
                <>
                  <span>
                    <span className="done-before">{pct(share.before)}</span> → <strong>{pct(share.after)}</strong>
                  </span>
                  <span className="done-row-facts">+{plural(addedOf(c), "fact")}</span>
                </>
              ) : (
                <>
                  {bars && <span className="done-before">{pct(share.before)}</span>}
                  <span className="tag tag-neutral">{declined ? "Not saved" : "Not reviewed"}</span>
                </>
              )}
            </span>
            <span className="done-row-toggle">{open ? "Hide ▴" : "Show ▾"}</span>
          </span>
        </button>
        {!saved && !reviewing && (
          <button type="button" className="btn btn-primary done-row-review" onClick={() => setReviewing(true)}>
            {declined ? "Review again" : "Review & save"}
          </button>
        )}
      </div>
      {reviewing ? (
        <div className="done-row-detail">
          <ScreenReview
            slug={c.slug}
            onSaved={() => {
              setReviewing(false);
              onSaved();
            }}
            onDeclined={() => {
              setReviewing(false);
              onDeclined();
            }}
          />
        </div>
      ) : (
        open && <Report c={c} onReview={() => setReviewing(true)} />
      )}
    </li>
  );
}

/** Review, then Done: one row per organisation in the run, each saved from here after its review. */
export function DoneReport({
  slugs,
  since,
  onStartOver,
  onPending,
  fallback,
}: {
  slugs: string[];
  /** When the run began, so only names it queued are shown. */
  since: number | null;
  onStartOver: () => void;
  /** How many organisations still wait for a review, so the step bar can say Review or Done. */
  onPending?: (n: number) => void;
  /** Shown until the numbers arrive, and instead of them when none come back. */
  fallback: ReactNode;
}) {
  const [all, setAll] = useState<ResearchCoverage[] | null>(null);
  const [queued, setQueued] = useState<QueueItem[]>([]);
  const [declined, setDeclined] = useState<string[]>([]);
  const key = slugs.join("|");

  useEffect(() => {
    let cancelled = false;
    // Between a pause's answer and the resume the run looks finished for a moment; don't dry-run every save for that.
    const wait = setTimeout(async () => {
      const [found, queue] = await Promise.all([
        Promise.all(
          key.split("|").map((slug) => get<ResearchCoverage>(`/api/ingest/research/${encodeURIComponent(slug)}/coverage`)),
        ),
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

  const pending = all === null ? null : all.filter((c) => !isSaved(c) && !declined.includes(c.slug)).length;
  useEffect(() => {
    if (pending !== null) onPending?.(pending);
  }, [pending, onPending]);

  async function reload(slug: string) {
    const fresh = await get<ResearchCoverage>(`/api/ingest/research/${encodeURIComponent(slug)}/coverage`);
    if (fresh) setAll((prev) => (prev ?? []).map((c) => (c.slug === slug ? fresh : c)));
  }

  if (all === null || all.length === 0) return <>{fallback}</>;

  const saved = all.filter(isSaved);
  const shares = saved.map(completeness);
  const avg = (pick: (s: { before: number; after: number }) => number) =>
    shares.reduce((n, s) => n + pick(s), 0) / Math.max(1, shares.length);
  const added = saved.reduce((n, c) => n + addedOf(c), 0);
  const reviewing = (pending ?? 0) > 0;
  const title = reviewing
    ? "Review what Sangam found"
    : saved.length > 0
      ? `Saved ${plural(saved.length, "organisation")}`
      : "Nothing saved";
  const savedLine =
    saved.length === 0
      ? ""
      : `${saved.length === 1 ? "The saved profile is" : "Saved profiles are"} now ${pct(avg((s) => s.after))} complete${
          saved.length === 1 ? "" : " on average"
        }, up from ${pct(avg((s) => s.before))}. ${plural(added, "new fact")} added, each linked to its proof.`;
  const sub = reviewing
    ? `${plural(pending ?? 0, "organisation")} to review. Open each one, check what was found and save what you want to keep, in any order.${
        savedLine ? ` ${savedLine}` : ""
      }`
    : savedLine || "Nothing from this run was saved. Each organisation's research is kept under Researched recently.";

  return (
    <section className="done" aria-label={reviewing ? "Review" : "Done"}>
      <div className="import-head">
        <h1 className="import-h1">{title}</h1>
        <p className="import-sub">{sub}</p>
      </div>

      <div className="done-table">
        <div className="done-legend" aria-hidden>
          <span data-part="kept">Already in Sangam</span>
          <span data-part="added">Added now</span>
          <span className="done-legend-end">Profile complete</span>
        </div>
        <ul className="done-rows">
          {all.map((c) => (
            <OrgRow
              key={c.slug}
              c={c}
              declined={declined.includes(c.slug)}
              onSaved={() => {
                setDeclined((prev) => prev.filter((s) => s !== c.slug));
                void reload(c.slug);
              }}
              onDeclined={() => setDeclined((prev) => (prev.includes(c.slug) ? prev : [...prev, c.slug]))}
            />
          ))}
        </ul>
      </div>

      {queued.length > 0 && (
        <div className="done-queued">
          <span className="card-kicker">
            {queued.length === 1 ? "One name needs a person" : `${queued.length} names need a person`}
          </span>
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
