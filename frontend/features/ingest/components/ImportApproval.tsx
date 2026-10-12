"use client";

import { useEffect, useState } from "react";
import { useInterrupt } from "@copilotkit/react-core/v2";
import { call } from "@/features/ask/lib/rest";
import { pausedAction } from "../lib/sourcePick";
import { PauseSignal } from "./PauseSignal";

type Plan = { goal: string; funders: string; years: string; sources: string; feeds: string };

/** What a paused run_import_now would pull; null when the interrupt is not one. */
export function pausedImport(value: unknown): Plan | null {
  const action = pausedAction(value, "run_import_now");
  if (!action) return null;
  const text = (k: string) => (typeof action.args?.[k] === "string" ? (action.args[k] as string) : "");
  return {
    goal: text("goal"),
    funders: text("funders"),
    years: text("years"),
    sources: text("sources"),
    feeds: text("feeds"),
  };
}

type NewsPlan = {
  everyone: boolean;
  subjects: number;
  records: number;
  searches: number;
  cost_usd: number;
  matched: string[];
  feeds: string[];
  unmatched: string[];
};

const isNews = (plan: Plan) => plan.sources.includes("tavily_news");

/** The news pull's one plan line, from the same plan the pull will run. */
function NewsLine({ funders, feeds }: { funders: string; feeds: string }) {
  const [line, setLine] = useState("Working out what this pull would search…");
  useEffect(() => {
    const query = `names=${encodeURIComponent(funders)}&feeds=${encodeURIComponent(feeds)}`;
    call<NewsPlan>(`/api/ingest/news-runs/plan?${query}`)
      .then((p) => {
        const cost = `about ${p.searches} searches · about $${p.cost_usd.toFixed(2)}`;
        const topics = p.feeds.join(", ");
        const named = p.everyone
          ? `News for everyone in Sangam (${p.records} organisations and funders)`
          : p.matched.length
            ? `News for ${p.matched.join(", ")} (their own news)`
            : "";
        const who = named && topics ? `${named}, plus topic news: ${topics}` : named || (topics && `Topic news: ${topics}`);
        const missing = p.unmatched.length ? `No Registry record for: ${p.unmatched.join(", ")}` : "";
        setLine([who && `${who} · ${cost}`, missing].filter(Boolean).join(". "));
      })
      .catch(() => setLine("Could not work out the plan; approving still runs the pull."));
  }, [funders, feeds]);
  return <span className="import-pick-text">{line}</span>;
}

function Card({ plan, onDecide }: { plan: Plan; onDecide: (approve: boolean) => void }) {
  const [sent, setSent] = useState(false);
  const decide = (approve: boolean) => {
    setSent(true);
    onDecide(approve);
  };
  if (isNews(plan))
    return (
      <section className="import-pick" aria-label="Approve this news pull">
        <div className="import-head">
          <span className="card-kicker">Sangam needs your answer</span>
          <strong className="import-pick-title">Pull the latest news?</strong>
          <NewsLine funders={plan.funders} feeds={plan.feeds} />
        </div>
        <div className="import-pick-actions">
          <button type="button" className="btn btn-primary" onClick={() => decide(true)} disabled={sent}>
            Pull the news
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => decide(false)} disabled={sent}>
            Don&apos;t pull
          </button>
        </div>
      </section>
    );
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
