"use client";

import { useState } from "react";
import { useInterrupt } from "@copilotkit/react-core/v2";
import { pausedAction } from "../lib/sourcePick";
import { PauseSignal } from "./PauseSignal";

type Plan = { goal: string; funders: string; years: string; sources: string };

/** What a paused run_import_now would pull; null when the interrupt is not one. */
export function pausedImport(value: unknown): Plan | null {
  const action = pausedAction(value, "run_import_now");
  if (!action) return null;
  const text = (k: string) => (typeof action.args?.[k] === "string" ? (action.args[k] as string) : "");
  return { goal: text("goal"), funders: text("funders"), years: text("years"), sources: text("sources") };
}

function Card({ plan, onDecide }: { plan: Plan; onDecide: (approve: boolean) => void }) {
  const [sent, setSent] = useState(false);
  const decide = (approve: boolean) => {
    setSent(true);
    onDecide(approve);
  };
  return (
    <section className="import-pick" aria-label="Approve this import">
      <div className="import-head">
        <span className="card-kicker">Sangam needs your answer</span>
        <strong className="import-pick-title">Write this import to the catalog?</strong>
        <span className="import-pick-text">{plan.goal || "No goal given."}</span>
        <span className="import-pick-text">
          Funders: {plan.funders || "whatever was published most recently"} · Years: {plan.years || "the most recent"} · Sources:{" "}
          {plan.sources || "every registered source"}
        </span>
      </div>
      <div className="import-pick-actions">
        <button type="button" className="btn btn-primary" onClick={() => decide(true)} disabled={sent}>
          Approve and write
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => decide(false)} disabled={sent}>
          Don&apos;t write
        </button>
      </div>
    </section>
  );
}

/** Shows the approval while the run is paused on run_import_now (HumanInTheLoopMiddleware). */
export function ImportApproval({ agentId, onPaused }: { agentId: string; onPaused: (paused: boolean) => void }) {
  return useInterrupt({
    agentId,
    renderInChat: false,
    enabled: (event) => pausedImport(event.value) !== null,
    render: ({ event, resolve }) => {
      const plan = pausedImport(event.value);
      return plan ? (
        <>
          <Card
            key={JSON.stringify(event.value)}
            plan={plan}
            onDecide={(approve) => void resolve({ decisions: [{ type: approve ? "approve" : "reject" }] })}
          />
          <PauseSignal onPaused={onPaused} />
        </>
      ) : (
        <></>
      );
    },
  });
}
