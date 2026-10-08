"use client";

import { useState } from "react";
import type { TraceStep } from "@/lib/useAgentChat";

/** The name the main agent put before the em dash, e.g. "KABIL — find …". */
function subjectOf(args: any): string {
  const description: string = args?.description ?? "";
  const [head] = description.split(/\s[—–-]\s/, 1);
  const subject = (head ?? "").trim();
  return subject && subject.length <= 60 ? subject : description.slice(0, 60) || "a task";
}

function briefOf(args: any): string {
  const description: string = args?.description ?? "";
  const parts = description.split(/\s[—–-]\s/);
  return (parts.length > 1 ? parts.slice(1).join(" — ") : description).trim();
}

/** A count, from either the summary's number or an older result's array. */
function numberOr(count: unknown, list: unknown): number | undefined {
  if (typeof count === "number") return count;
  return Array.isArray(list) ? list.length : undefined;
}

/** Which subagent this card is for. deepagents passes the type alongside the
 *  description; before this the board assumed every task was a researcher. */
type Kind = "researcher" | "writer";

function kindOf(args: any): Kind {
  return args?.subagent_type === "catalog-writer" ? "writer" : "researcher";
}

type Outcome = {
  state: "working" | "done" | "stopped";
  status?: string;
  facts?: number;
  sources?: number;
  slug?: string;
  note?: string;
  /** Writer only. */
  rows?: number;
  tables?: number;
  held?: string[];
};

/**
 * A researcher is finished when its RESULT arrives — not when `running` goes
 * false. `running` is run-wide, so at the end of a run every unfinished
 * researcher would otherwise read as "done".
 */
function outcomeOf(step: TraceStep): Outcome {
  if (step.result === null) {
    return step.running
      ? { state: "working" }
      : { state: "stopped", note: "the run ended before this one reported" };
  }
  try {
    const parsed = JSON.parse(step.result);
    if (kindOf(step.args) === "writer") {
      const rows: number = parsed.rows_written ?? 0;
      // A conflict is a decision for a person too, so it is shown beside what was held back.
      const held: string[] = [
        ...(Array.isArray(parsed.held_back) ? parsed.held_back : []),
        ...(Array.isArray(parsed.conflicts) ? parsed.conflicts : []),
      ];
      const tables = Array.isArray(parsed.tables_written) ? parsed.tables_written.length : 0;
      // Nothing written and nothing explaining it is the report that reads as
      // success and is not one.
      const state = rows === 0 && held.length === 0 ? "stopped" : "done";
      return {
        state,
        rows,
        tables,
        held,
        slug: parsed.entity_name ?? parsed.slug,
        note: held[0] ?? (rows === 0 ? "nothing reached the catalog" : undefined),
      };
    }
    // The researcher returns a ResearchSummary: counts, not the findings
    // themselves, which went to the database through save_research. Older
    // results carried the arrays, so both shapes are read.
    const facts = numberOr(parsed.fact_count, parsed.findings);
    const sources = numberOr(parsed.source_count, parsed.sources_read);
    const status: string | undefined = parsed.status;
    const slug = parsed.canonical_name ?? parsed.entity_name;
    if (status === "not_found" || status === "wrong_entity") {
      return { state: "stopped", status, facts, sources, note: parsed.stopped_reason };
    }
    return { state: "done", status, facts, sources, slug, note: parsed.stopped_reason };
  } catch {
    // A researcher without a response_format returns prose, which is still a
    // finished result — just one we cannot count.
    return { state: "done", note: step.result.slice(0, 90) };
  }
}

const TONE: Record<Outcome["state"], string> = {
  working: "var(--color-accent-900)",
  done: "var(--color-accent-2-900)",
  stopped: "var(--color-bad)",
};

/** One box per researcher, collapsing to a single line once they have all reported. */
export function SubagentBoard({ steps }: { steps: TraceStep[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  if (steps.length === 0) return null;

  const outcomes = steps.map((s) => [s, outcomeOf(s)] as const);
  const working = outcomes.filter(([, o]) => o.state === "working").length;
  const done = outcomes.filter(([, o]) => o.state === "done").length;
  const stopped = outcomes.filter(([, o]) => o.state === "stopped").length;
  const researchers = steps.filter((s) => kindOf(s.args) === "researcher").length;
  const writers = steps.length - researchers;
  // Expanded while anything is working, a summary line once they have finished.
  const expanded = working > 0;

  const tally = [
    researchers > 0 ? `${researchers} researcher${researchers === 1 ? "" : "s"}` : null,
    writers > 0 ? `${writers} writer${writers === 1 ? "" : "s"}` : null,
    working > 0 ? `${working} working` : null,
    done > 0 ? `${done} done` : null,
    stopped > 0 ? `${stopped} stopped` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  // Writers only start once every researcher has returned, because parallel
  // tasks resolve together. Saying so beats looking idle.
  const waiting = writers === 0 && working > 0 && done > 0;

  return (
    <section
      style={{
        border: "1px solid var(--color-divider)",
        borderRadius: 10,
        padding: "11px 13px",
        background: "var(--color-surface)",
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <strong style={{ fontSize: "var(--fs-sm)" }}>{tally}</strong>
        <span style={{ fontSize: "var(--fs-xs)", color: "var(--color-muted)" }}>
          {waiting
            ? "one organisation each · writing to the catalog starts once all have reported"
            : "one organisation each, separate context"}
        </span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: expanded ? "repeat(auto-fill, minmax(230px, 1fr))" : "1fr",
          gap: expanded ? 10 : 6,
          marginTop: 10,
        }}
      >
        {outcomes.map(([step, o]) => {
          const isOpen = expanded || openId === step.id;
          return (
            <article
              key={step.id}
              style={{
                border: "1px solid var(--color-divider)",
                borderLeft: `3px solid ${TONE[o.state]}`,
                borderRadius: 8,
                padding: isOpen ? "9px 11px" : "6px 11px",
              }}
            >
              <button
                type="button"
                onClick={() => setOpenId(openId === step.id ? null : step.id)}
                disabled={expanded}
                style={{
                  all: "unset",
                  cursor: expanded ? "default" : "pointer",
                  display: "flex",
                  alignItems: "baseline",
                  gap: 8,
                  width: "100%",
                }}
                aria-expanded={isOpen}
              >
                {o.state === "working" && (
                  <span
                    aria-hidden
                    className="sangam-pulse"
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      background: TONE.working,
                      flexShrink: 0,
                    }}
                  />
                )}
                <strong style={{ fontSize: "var(--fs-sm)" }}>{subjectOf(step.args)}</strong>
                {kindOf(step.args) === "writer" && (
                  <span style={{ fontSize: "var(--fs-xs)", color: "var(--color-muted)" }}>
                    → catalog
                  </span>
                )}
                <span
                  style={{ marginLeft: "auto", fontSize: "var(--fs-xs)", color: TONE[o.state] }}
                >
                  {o.state === "working"
                    ? kindOf(step.args) === "writer"
                      ? "writing…"
                      : "researching…"
                    : o.state === "stopped"
                      ? (o.status ?? "stopped")
                      : kindOf(step.args) === "writer"
                        ? `✓ ${o.rows ?? 0} row${o.rows === 1 ? "" : "s"} in ${o.tables ?? 0} table${o.tables === 1 ? "" : "s"}`
                        : `✓ ${o.facts ?? 0} facts`}
                </span>
              </button>

              {isOpen && (
                <div style={{ marginTop: 5, fontSize: "var(--fs-xs)", lineHeight: 1.45 }}>
                  <p style={{ margin: 0, color: "var(--color-muted)" }}>
                    {o.state === "working"
                      ? briefOf(step.args).slice(0, 130)
                      : (o.note ?? briefOf(step.args).slice(0, 130))}
                  </p>
                  {o.state === "done" && o.sources !== undefined && (
                    <p style={{ margin: "3px 0 0", color: "var(--color-muted)" }}>
                      {o.sources} source{o.sources === 1 ? "" : "s"} read
                      {o.status && o.status !== "complete" ? ` · ${o.status}` : ""}
                    </p>
                  )}
                  {/* Held back is a decision for a person, so it is shown in
                      full rather than counted. */}
                  {o.held !== undefined && o.held.length > 0 && (
                    <ul style={{ margin: "4px 0 0", paddingLeft: 15, color: "var(--color-bad)" }}>
                      {o.held.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
