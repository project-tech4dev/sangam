"use client";

import { useState } from "react";
import { useInterrupt } from "@copilotkit/react-core/v2";

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

type Paused = { slug: string; questions: Question[] };

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

/** The paused promote_research and its questions, or null when the interrupt is not one. */
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
  return { slug: typeof args.slug === "string" ? args.slug : "", questions: save.questions as Question[] };
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
  const muted = { color: "var(--color-muted)", fontSize: "var(--fs-xs)" } as const;
  if (q.case === 4) {
    return (
      <span style={muted}>
        Research says “{q.new_name}”; the catalog has “{q.stored_name}” {q.row}
      </span>
    );
  }
  return (
    <span style={{ display: "grid", gap: 2 }}>
      {Object.entries(q.changes ?? {}).map(([column, c]) => (
        <span key={column} style={{ fontSize: "var(--fs-sm)" }}>
          {column}: {show(c.old)}
          <span style={muted}>{dated(q.stored_as_of)}</span> → {show(c.new)}
          <span style={muted}>{dated(q.new_as_of)}</span>
        </span>
      ))}
      <span style={muted}>
        The research source is older or undated, so it does not replace the stored value on its own. {q.row}
      </span>
    </span>
  );
}

/** The run is paused on promote_research. Staff answer each question with a button, then save. */
export function SaveQuestionCard({
  paused,
  onDecide,
}: {
  paused: Paused;
  onDecide: (decision: SaveDecision) => void;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [sent, setSent] = useState(false);
  const answered = paused.questions.filter((q) => answers[q.id]).length;

  function decide(decision: SaveDecision) {
    setSent(true);
    onDecide(decision);
  }

  return (
    <section
      aria-label="Questions before saving"
      style={{
        border: "1px solid var(--color-divider)",
        borderRadius: "var(--radius-surface)",
        background: "var(--color-surface)",
        padding: 16,
        display: "grid",
        gap: 12,
      }}
    >
      <div style={{ display: "grid", gap: 4 }}>
        <strong>
          {paused.questions.length === 1 ? "One question" : `${paused.questions.length} questions`} before{" "}
          {paused.slug || "this research"} is saved
        </strong>
        <span style={{ color: "var(--color-muted)", fontSize: "var(--fs-sm)" }}>
          The run is paused until you answer. Everything else is already decided.
        </span>
      </div>

      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 12 }}>
        {paused.questions.map((q) => (
          <li key={q.id} style={{ display: "grid", gap: 6 }}>
            <span style={{ fontWeight: 600, fontSize: "var(--fs-sm)" }}>
              {q.table.replace(/_/g, " ")} · {q.label}
            </span>
            <Detail q={q} />
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
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

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() =>
            decide({
              type: "edit",
              edited_action: { name: "promote_research", args: { slug: paused.slug, decisions: answers } },
            })
          }
          disabled={sent || answered < paused.questions.length}
        >
          Save with these answers
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
export function SaveQuestions({ agentId }: { agentId: string }) {
  return useInterrupt({
    agentId,
    renderInChat: false,
    enabled: (event) => pausedSave(event.value) !== null,
    render: ({ event, resolve }) => {
      const paused = pausedSave(event.value);
      return paused ? (
        <SaveQuestionCard paused={paused} onDecide={(decision) => void resolve({ decisions: [decision] })} />
      ) : (
        <></>
      );
    },
  });
}
