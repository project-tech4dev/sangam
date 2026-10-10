"use client";

import { useEffect, useState } from "react";
import { EntityMark } from "@/components/ui/primitives";
import { authHeaders } from "@/lib/api/auth-headers";
import { formatInr } from "@/lib/format";
import { KIND_LABEL } from "../lib/words";
import type { ResearchReview, ReviewQuestion } from "../lib/types";
import { Answer, Missing } from "./ReviewFields";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";
const SHOWN = 10;

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
  update: "Use the new answer",
  new: "Keep both",
  skip: "Skip",
};
// Case 4 asks whether two names are one organisation, so its choices answer that.
const SAME_OR_NOT: Record<string, string> = { update: "Yes, the same", new: "No, they're different", skip: "Not sure — leave it" };

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

const quoted = (value: string) => `“${value}”`;

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
  const dated = (as_of: string | null) => (as_of ? `from ${as_of}` : "no date");
  return (
    <div className="review-question">
      <strong className="review-question-title">
        {q.case === 4 ? "Is this the same organisation?" : `${q.topic}${q.about ? ` · ${q.about}` : ""}`}
      </strong>
      {q.case === 4 ? (
        <span className="review-question-text">
          The research found {quoted(q.new_name ?? "")}. Sangam has {quoted(q.stored_name ?? "")}. Saving them as one would mix up
          their records, and that can&apos;t be undone.
        </span>
      ) : (
        q.fields.map((f) => (
          <span key={f.label} className="review-question-text">
            {f.label}: Sangam already says {quoted(shown(f.old, f.money))} ({dated(q.stored_as_of)}). The new research says{" "}
            {quoted(shown(f.new, f.money))} ({dated(q.new_as_of)}). Which should the profile show?
          </span>
        ))
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
            {(q.case === 4 ? SAME_OR_NOT[c.value] : CHOICE_WORDS[c.value]) || c.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** The Review step: what was found, with proof, and any question to answer before it is saved. */
export function ReviewCard({
  slug,
  questions,
  onDecide,
  inline = false,
}: {
  /** Empty when the agent saves everything researched in the run at once. */
  slug: string;
  /** A paused save's own questions; without them, the review's questions are the ones asked. */
  questions?: PausedQuestion[];
  /** May return a promise: a rejection shows its message and lets the person try again. */
  onDecide: (decision: SaveDecision) => void | Promise<void>;
  /** Opened inside a Done or Researched recently row, which already names the organisation. */
  inline?: boolean;
}) {
  const [review, setReview] = useState<ResearchReview | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [all, setAll] = useState(false);
  const [save, setSave] = useState(true);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
  const asked = questions ? questions.map((q) => worded.get(q.id) ?? fallback(q)) : (review?.questions ?? []);
  const n = asked.length;
  const left = save ? n - asked.filter((q) => answers[q.id]).length : 0;
  const loading = Boolean(slug) && review === null && !failed;
  const name = slug ? review?.name || slug : "Everything researched in this run";
  const found = review?.answers ?? [];
  const confirmed = found.filter((a) => a.tag === "confirmed").length;
  const total = found.length + (review?.missing.length ?? 0);
  const hasDetail = found.length + (review?.missing.length ?? 0) > 0;

  async function decide(decision: SaveDecision) {
    setSent(true);
    setError(null);
    try {
      await onDecide(decision);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSent(false);
    }
  }

  function finish() {
    if (!save) return void decide({ type: "reject", message: "Staff chose not to save this research." });
    void decide({ type: "edit", edited_action: { name: "promote_research", args: { slug, decisions: answers } } });
  }

  return (
    <section aria-label="Review before saving" className="review">
      {!inline && (
        <div className="import-head">
          <h1 className="import-h1">Here&apos;s what Sangam found</h1>
          <p className="import-sub">
            It&apos;s ticked to save — untick it if you don&apos;t want it{n > 0 ? ", and answer the questions" : ""}.
          </p>
        </div>
      )}

      <div className="review-table">
        <div className="review-row">
          <div className="review-row-head">
            <input
              type="checkbox"
              className="review-check"
              checked={save}
              onChange={() => setSave(!save)}
              disabled={sent}
              aria-label={`Save ${name}`}
            />
            <EntityMark name={name} size={32} />
            <div className="review-row-name">
              <strong>{name}</strong>
              {review && (
                <span className="review-row-sub">
                  {[review.kind ? KIND_LABEL[review.kind] : null, review.existing ? "Already in Sangam" : "New to Sangam"]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              )}
              {loading && <span className="review-row-sub">Getting the answers ready…</span>}
              {failed && <span className="review-row-sub">Sangam couldn&apos;t load the answers. You can still save or not.</span>}
            </div>
            {total > 0 && (
              <span className="review-row-count">
                {confirmed} of {total} confirmed
              </span>
            )}
            {hasDetail && (
              <button type="button" className="review-row-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
                {open ? "Hide answers" : "See answers"}
              </button>
            )}
          </div>

          {save &&
            asked.map((q) => (
              <Question
                key={q.id}
                q={q}
                chosen={answers[q.id]}
                onChoose={(value) => setAnswers((prev) => ({ ...prev, [q.id]: value }))}
                disabled={sent}
              />
            ))}

          {open && review && (
            <div className="review-row-detail">
              {(all ? found : found.slice(0, SHOWN)).map((a, i) => (
                <Answer key={`${a.concept}-${i}`} answer={a} />
              ))}
              {found.length > SHOWN && (
                <button type="button" className="review-more" onClick={() => setAll(!all)}>
                  {all ? "Show fewer" : `Show all ${found.length}`}
                </button>
              )}
              {review.missing.map((m) => (
                <Missing key={m.concept} m={m} />
              ))}
              {review.existing && review.kind !== "funder" && (
                <span className="review-row-note">
                  Sangam already has a profile for {review.name}. Saving only fills in answers that are empty there — nothing already
                  on the profile is changed.
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="review-actions">
        <button type="button" className="btn btn-primary" onClick={finish} disabled={sent || left > 0 || loading}>
          {sent && save ? "Saving…" : save ? (slug ? "Save 1 organisation" : "Save everything") : "Continue without saving"}
        </button>
        <span className="review-hint">
          {left > 0 ? `Answer ${left === 1 ? "the question" : `${left} questions`} above first.` : "Nothing is saved until you choose."}
        </span>
        {error && <span className="import-error">{error}</span>}
      </div>
    </section>
  );
}
