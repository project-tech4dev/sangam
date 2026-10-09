"use client";

import { useState } from "react";
import { useInterrupt } from "@copilotkit/react-core/v2";
import { PauseSignal } from "./PauseSignal";

type Change = { old: unknown; new: unknown };

/** One question SaveQuestions (backend/app/agent/middleware.py) put on the paused promote_research. */
type Question = {
  id: string;
  case: 3 | 4;
  table: string;
  label: string;
  row?: string | null;
  changes?: Record<string, Change>;
  stored_as_of?: string | null;
  new_as_of?: string | null;
  stored_name?: string;
  new_name?: string;
  choices: string[];
};

type Paused = { slug: string; questions: Question[]; planned: string[]; coverage: string };

/** One of LangChain's HumanInTheLoopMiddleware decisions; the run resumes with `{decisions: [it]}`. */
type SaveDecision =
  | { type: "edit"; edited_action: { name: string; args: Record<string, unknown> } }
  | { type: "reject"; message: string };

const CHOICE_LABELS: Record<string, string> = {
  update: "Update",
  keep: "Keep stored",
  new: "Add as new row",
  skip: "Skip",
};

/** The paused promote_research and what it would write, or null when the interrupt is not one. */
export function pausedSave(value: unknown): Paused | null {
  let request = value;
  if (typeof request === "string") {
    try {
      request = JSON.parse(request);
    } catch {
      return null;
    }
  }
  const actions = (request as { action_requests?: Record<string, unknown>[] } | null)?.action_requests;
  const save = actions?.find((a) => a?.name === "promote_research" && Array.isArray(a?.questions));
  if (!save) return null;
  const args = (save.args ?? {}) as { slug?: unknown };
  return {
    slug: typeof args.slug === "string" ? args.slug : "",
    questions: save.questions as Question[],
    planned: Array.isArray(save.planned) ? (save.planned as string[]) : [],
    coverage: typeof save.coverage === "string" ? save.coverage : "",
  };
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function dated(as_of?: string | null): string {
  return as_of ? ` (${as_of})` : " (undated)";
}

/** What the question is about: the changed values for case 3, the two names for case 4. */
function Detail({ q }: { q: Question }) {
  if (q.case === 4) {
    return (
      <span className="save-note">
        Research says “{q.new_name}”; the catalog has “{q.stored_name}” {q.row}
      </span>
    );
  }
  return (
    <span className="save-changes">
      {Object.entries(q.changes ?? {}).map(([column, c]) => (
        <span key={column} className="save-change">
          {column}: {show(c.old)}
          <span className="save-note">{dated(q.stored_as_of)}</span> → {show(c.new)}
          <span className="save-note">{dated(q.new_as_of)}</span>
        </span>
      ))}
      <span className="save-note">
        The research source is older or undated, so it does not replace the stored value on its own. {q.row}
      </span>
    </span>
  );
}

/** The run is paused on promote_research. Staff approve the write, answering any question first. */
export function SaveQuestionCard({
  paused,
  onDecide,
}: {
  paused: Paused;
  onDecide: (decision: SaveDecision) => void;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [sent, setSent] = useState(false);
  const n = paused.questions.length;
  const answered = paused.questions.filter((q) => answers[q.id]).length;
  const who = paused.slug || "this research";

  function decide(decision: SaveDecision) {
    setSent(true);
    onDecide(decision);
  }

  return (
    <section aria-label="Approve the catalog write" className="card save-card">
      <div className="save-head">
        <strong>
          {n === 0
            ? `Write ${who} to the catalog?`
            : `${n === 1 ? "One question" : `${n} questions`} before ${who} is saved`}
        </strong>
        <span className="save-sub">
          The run is paused until you decide. Nothing is written without your approval.
        </span>
        {paused.coverage && <span className="save-note">{paused.coverage}</span>}
      </div>

      {paused.planned.length > 0 && (
        <ul className="save-plan">
          {paused.planned.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}

      {n > 0 && (
        <ul className="save-list">
          {paused.questions.map((q) => (
            <li key={q.id} className="save-item">
              <span className="save-item-title">
                {q.table.replace(/_/g, " ")} · {q.label}
              </span>
              <Detail q={q} />
              <div className="save-choices">
                {q.choices.map((choice) => (
                  <button
                    key={choice}
                    type="button"
                    className="pill"
                    data-active={answers[q.id] === choice}
                    aria-pressed={answers[q.id] === choice}
                    onClick={() => setAnswers((prev) => ({ ...prev, [q.id]: choice }))}
                    disabled={sent}
                  >
                    {CHOICE_LABELS[choice] ?? choice}
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="save-actions">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() =>
            decide({
              type: "edit",
              edited_action: { name: "promote_research", args: { slug: paused.slug, decisions: answers } },
            })
          }
          disabled={sent || answered < n}
        >
          {n === 0 ? "Approve and write" : "Save with these answers"}
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => decide({ type: "reject", message: "Staff chose not to save this research." })}
          disabled={sent}
        >
          Don&apos;t save
        </button>
      </div>
    </section>
  );
}

/** Shows the question card while the run is paused on promote_research (HumanInTheLoopMiddleware). */
export function SaveQuestions({ agentId, onPaused }: { agentId: string; onPaused: (paused: boolean) => void }) {
  return useInterrupt({
    agentId,
    renderInChat: false,
    enabled: (event) => pausedSave(event.value) !== null,
    render: ({ event, resolve }) => {
      const paused = pausedSave(event.value);
      return paused ? (
        <>
          <SaveQuestionCard paused={paused} onDecide={(decision) => void resolve({ decisions: [decision] })} />
          <PauseSignal onPaused={onPaused} />
        </>
      ) : (
        <></>
      );
    },
  });
}
