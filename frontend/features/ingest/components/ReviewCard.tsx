"use client";

import { useEffect, useState } from "react";
import { EntityMark } from "@/components/ui/primitives";
import { authHeaders } from "@/lib/api/auth-headers";
import { formatInr } from "@/lib/format";
import { KIND_LABEL } from "../lib/words";
import type { ResearchReview, ReviewAnswer, ReviewFact, ReviewQuestion } from "../lib/types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";
const SHOWN = 10;
// Findings from a staff workbook cite this made-up host (backend app/ingest/staff_sources.py); it is not a page.
const STAFF_SOURCE = "https://staff-sources.sangam.invalid/";

/** A question as the paused promote_research carries it (backend app/agent/middleware.py). */
export type PausedQuestion = {
  id: string;
  case: 3 | 4;
  table: string;
  label: string;
  row?: string | null;
  changes?: Record<string, { old: unknown; new: unknown }>;
  stored_as_of?: string | null;
  new_as_of?: string | null;
  stored_name?: string;
  new_name?: string;
  choices: string[];
};

/** One of LangChain's HumanInTheLoopMiddleware decisions; the run resumes with `{decisions: [it]}`. */
export type SaveDecision =
  | { type: "edit"; edited_action: { name: string; args: Record<string, unknown> } }
  | { type: "reject"; message: string };

const CHOICE_WORDS: Record<string, string> = {
  keep: "Keep what Sangam has",
  update: "Use the new one",
  new: "Add it separately",
  skip: "Skip",
};
// Case 4 asks whether two names are one organisation, so its choices answer that.
const SAME_OR_NOT: Record<string, string> = { update: "Same — update it", new: "Different — add it", skip: "Skip" };

const phrase = (s: string) => {
  const t = s.replace(/_/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
};

/** Used only when the review could not be fetched: the payload's own question, in rough words. */
function fallback(q: PausedQuestion): ReviewQuestion {
  return {
    id: q.id,
    case: q.case,
    topic: phrase(q.table),
    about: q.label,
    fields: Object.entries(q.changes ?? {}).map(([col, c]) => ({ label: phrase(col), old: c.old, new: c.new, money: false })),
    stored_as_of: q.stored_as_of ?? null,
    new_as_of: q.new_as_of ?? null,
    stored_name: q.stored_name ?? null,
    new_name: q.new_name ?? null,
    choices: q.choices.map((value) => ({ value, label: CHOICE_WORDS[value] ?? phrase(value) })),
  };
}

function shown(value: unknown, money: boolean): string {
  if (value === null || value === undefined || value === "") return "—";
  if (money && (typeof value === "number" || (typeof value === "string" && value.trim() !== "" && !isNaN(Number(value)))))
    return formatInr(Number(value));
  if (Array.isArray(value)) return value.map((v) => shown(v, false)).join(", ");
  if (typeof value === "object") {
    const text = (value as { text?: unknown }).text;
    return typeof text === "string" ? text : Object.values(value).filter((v) => typeof v !== "object").join(", ");
  }
  return String(value);
}

const fact = (f: ReviewFact) => {
  const value = f.money && typeof f.value === "number" ? formatInr(f.value) : String(f.value);
  return f.label ? `${f.label}: ${value}` : value;
};

function Source({ answer }: { answer: ReviewAnswer }) {
  if (!answer.source_url) return null;
  if (answer.source_url.startsWith(STAFF_SOURCE)) return <span className="review-source">Your team&apos;s spreadsheet</span>;
  return (
    <a className="review-source" href={answer.source_url} target="_blank" rel="noreferrer">
      {answer.source_name || "Source"}
    </a>
  );
}

function Answer({ answer }: { answer: ReviewAnswer }) {
  const [open, setOpen] = useState(false);
  const confirmed = answer.tag === "confirmed";
  return (
    <li className="review-answer">
      <div className="review-answer-head">
        <strong>{answer.topic}</strong>
        {answer.year && <span className="review-year">{answer.year}</span>}
        <span className={`tag ${confirmed ? "tag-accent-2" : "tag-accent"}`}>{confirmed ? "Confirmed" : "Self-reported"}</span>
      </div>
      {answer.facts.length > 0 && <p className="review-facts">{answer.facts.map(fact).join(" · ")}</p>}
      {(answer.quote || answer.source_url) && (
        <button type="button" className="review-proof-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide proof" : "See proof"}
        </button>
      )}
      {open && (
        <div className="review-proof">
          {answer.quote && <blockquote>“{answer.quote}”</blockquote>}
          <Source answer={answer} />
        </div>
      )}
    </li>
  );
}

function Question({
  q,
  chosen,
  onChoose,
  disabled,
}: {
  q: ReviewQuestion;
  chosen: string | undefined;
  onChoose: (value: string) => void;
  disabled: boolean;
}) {
  const dated = (as_of: string | null) => (as_of ? ` (${as_of})` : " (no date)");
  return (
    <li className="review-question">
      <span className="review-question-title">
        {q.topic}
        {q.about && ` · ${q.about}`}
      </span>
      {q.case === 4 ? (
        <span className="review-question-text">
          The research found “{q.new_name}”. Sangam already has “{q.stored_name}”. Are they the same?
        </span>
      ) : (
        <>
          {q.fields.map((f) => (
            <span key={f.label} className="review-question-text">
              {f.label}: Sangam has {shown(f.old, f.money)}
              <span className="review-note">{dated(q.stored_as_of)}</span>, the research says {shown(f.new, f.money)}
              <span className="review-note">{dated(q.new_as_of)}</span>
            </span>
          ))}
          <span className="review-note">The new source is older or has no date, so Sangam won&apos;t replace this without you.</span>
        </>
      )}
      <div className="review-choices">
        {q.choices.map((c) => (
          <button
            key={c.value}
            type="button"
            className="pill"
            data-active={chosen === c.value}
            aria-pressed={chosen === c.value}
            onClick={() => onChoose(c.value)}
            disabled={disabled}
          >
            {(q.case === 4 && SAME_OR_NOT[c.value]) || c.label}
          </button>
        ))}
      </div>
    </li>
  );
}

/** The Review step: what was found, with proof, and any question to answer before it is saved. */
export function ReviewCard({
  slug,
  questions,
  onDecide,
}: {
  /** Empty when the agent saves everything researched in the run at once. */
  slug: string;
  questions: PausedQuestion[];
  onDecide: (decision: SaveDecision) => void;
}) {
  const [review, setReview] = useState<ResearchReview | null>(null);
  const [failed, setFailed] = useState(false);
  const [all, setAll] = useState(false);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [sent, setSent] = useState(false);

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/ingest/research/${encodeURIComponent(slug)}/review`, {
          headers: await authHeaders(),
        });
        if (!res.ok) throw new Error(String(res.status));
        const body: ResearchReview = await res.json();
        if (!cancelled) setReview(body);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [slug]);

  // The payload's questions are the ones to answer; the review only says them in words.
  const worded = new Map((review?.questions ?? []).map((q) => [q.id, q]));
  const asked = questions.map((q) => worded.get(q.id) ?? fallback(q));
  const n = asked.length;
  const answered = asked.filter((q) => answers[q.id]).length;
  const loading = Boolean(slug) && review === null && !failed;
  const name = review?.name || slug || "everything researched in this run";

  function decide(decision: SaveDecision) {
    setSent(true);
    onDecide(decision);
  }

  return (
    <section aria-label="Review before saving" className="card review-card">
      <div className="review-head">
        <EntityMark name={name} size={40} />
        <div className="review-head-text">
          <span className="card-kicker">Ready for your review</span>
          <strong className="review-name">{slug ? name : "Save everything researched in this run?"}</strong>
          {review && (
            <span className="review-sub">
              {[review.kind ? KIND_LABEL[review.kind] : null, review.existing ? "Already in Sangam" : "New to Sangam"]
                .filter(Boolean)
                .join(" · ")}
            </span>
          )}
        </div>
      </div>

      {review?.existing && review.kind !== "funder" && (
        <p className="review-note">Saving only fills in answers that are empty.</p>
      )}
      {loading && <span className="muted">Getting the answers ready…</span>}
      {failed && <span className="review-note">Sangam couldn&apos;t load the answers. You can still save or not.</span>}

      {review && review.answers.length > 0 && (
        <div className="review-section">
          <span className="review-label">
            Sangam found {review.answers.length} answer{review.answers.length === 1 ? "" : "s"}
          </span>
          <ul className="review-answers">
            {(all ? review.answers : review.answers.slice(0, SHOWN)).map((a, i) => (
              <Answer key={`${a.concept}-${i}`} answer={a} />
            ))}
          </ul>
          {review.answers.length > SHOWN && (
            <button type="button" className="review-proof-toggle" onClick={() => setAll(!all)}>
              {all ? "Show fewer" : `Show all ${review.answers.length}`}
            </button>
          )}
        </div>
      )}

      {review && review.missing.length > 0 && (
        <div className="review-section">
          <span className="review-label">Not found</span>
          <ul className="review-missing">
            {review.missing.map((m) => (
              <li key={m.concept}>
                <span>{m.topic}</span>
                <span className={`tag ${m.tag === "couldnt_read" ? "tag-neutral" : "tag-outline"}`}>
                  {m.tag === "couldnt_read" ? "Couldn't read" : "Not mentioned"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {review && review.saves.length > 0 && (
        <div className="review-section">
          <span className="review-label">What saving adds</span>
          <ul className="review-saves">
            {review.saves.map((s) => (
              <li key={s.concept}>
                {s.topic}:{" "}
                {[s.added && `${s.added} new`, s.updated && `${s.updated} updated`].filter(Boolean).join(", ") || "nothing new"}
              </li>
            ))}
          </ul>
        </div>
      )}

      {n > 0 && (
        <div className="review-section">
          <span className="review-label">Before saving, {n === 1 ? "one question" : `${n} questions`}</span>
          <ul className="review-questions">
            {asked.map((q) => (
              <Question
                key={q.id}
                q={q}
                chosen={answers[q.id]}
                onChoose={(value) => setAnswers((prev) => ({ ...prev, [q.id]: value }))}
                disabled={sent}
              />
            ))}
          </ul>
        </div>
      )}

      <div className="review-actions">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() =>
            decide({ type: "edit", edited_action: { name: "promote_research", args: { slug, decisions: answers } } })
          }
          disabled={sent || answered < n}
        >
          Save to Sangam
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => decide({ type: "reject", message: "Staff chose not to save this research." })}
          disabled={sent}
        >
          Don&apos;t save
        </button>
        <span className="review-note">Nothing is saved until you choose.</span>
      </div>
    </section>
  );
}
