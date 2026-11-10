"use client";

import { useMemo, useState } from "react";
import { LoginForm } from "@/features/auth/login-form";
import { AnswerCard } from "../components/AnswerCard";
import { ComposerNotice } from "../components/ComposerNotice";
import { TraceCard } from "../components/TraceCard";
import type { RegistryIndex } from "../lib/citations";
import { savePendingQuestion } from "../lib/pendingQuestion";
import {
  EXAMPLE_QUESTIONS,
  SAMPLE_ANSWER,
  SAMPLE_CRITERIA,
  SAMPLE_FOLLOW_UPS,
  SAMPLE_INDEX,
  SAMPLE_QUESTION,
  SAMPLE_TRACE,
} from "./sample";

const SIGNED_IN_EXTRAS = [
  { title: "Doc vault", body: "Your organisation's documents, ready to draw on when you write a proposal." },
  { title: "Media & signals", body: "News and posts about NGOs and funders, to affirm or push back on." },
  { title: "RFP watch", body: "Open calls that match your work, gathered every week. Coming soon." },
];

/**
 * Ask Sangam for a visitor who is not signed in. It shows what an answer looks like
 * without calling the agent; asking anything — typing, an example, a follow-up — opens
 * sign-in, and the question is waiting in the workspace afterwards.
 */
export function AskPreview({ initialQuestion = null }: { initialQuestion?: string | null }) {
  const [draft, setDraft] = useState(initialQuestion ?? "");
  const [signingIn, setSigningIn] = useState(false);

  const index: RegistryIndex = useMemo(
    () => ({
      orgs: new Map(SAMPLE_INDEX.orgs),
      funders: new Map(SAMPLE_INDEX.funders),
      scores: new Map(SAMPLE_INDEX.scores),
      activities: new Map(),
    }),
    [],
  );

  function ask(question?: string) {
    const text = (question ?? draft).trim();
    if (!text) return;
    setDraft(text);
    setSigningIn(true);
  }

  return (
    <div data-testid="ask-preview" className="page flex flex-col gap-10">
      <section className="flex w-full max-w-215 flex-col gap-5">
        <div className="flex flex-col gap-2">
          <div className="eyebrow">Ask Sangam</div>
          <h1 className="text-4xl" style={{ letterSpacing: "-0.015em" }}>Ask the base a question</h1>
          <p className="m-0 max-w-[62ch] text-base text-(--color-muted)">
            Ask about NGOs, funders and how well they fit. Every answer shows the steps it took and
            cites the rows it used — and says so when the base has no answer.
          </p>
        </div>

        <div className="card elev-sm">
          <textarea
            className="input"
            style={{ border: "none", padding: 4, minHeight: 48 }}
            placeholder="Ask about an organisation, a funder, or a fit…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") ask();
            }}
          />
          <div className="flex items-center gap-2.5">
            <span className="muted-2 text-xs">Sign in to ask · ⌘↵</span>
            <button className="btn btn-primary ml-auto" onClick={() => ask()} disabled={!draft.trim()}>
              Ask Sangam
            </button>
          </div>
          <ComposerNotice />
        </div>

        <div className="flex flex-wrap gap-2">
          {EXAMPLE_QUESTIONS.map((q) => (
            <button key={q} className="pill" onClick={() => ask(q)}>
              {q}
            </button>
          ))}
        </div>
      </section>

      <section className="flex w-full max-w-215 flex-col gap-3" aria-labelledby="sample-heading">
        <div className="flex items-baseline gap-2.5">
          <h2 id="sample-heading" className="text-xl font-semibold">
            What an answer looks like
          </h2>
          <span className="muted-2 text-xs">A sample, from the base&apos;s real fit-score rows</span>
        </div>

        <div className="card" style={{ gap: 16 }}>
          <div className="flex items-start gap-3">
            <div
              aria-hidden
              className="flex size-8.5 flex-none items-center justify-center rounded-full bg-(--color-neutral-700) text-xs font-bold text-white"
            >
              You
            </div>
            <div className="pt-1 font-(family-name:--font-heading) text-base font-semibold">{SAMPLE_QUESTION}</div>
          </div>
          <TraceCard steps={SAMPLE_TRACE} streaming={false} />
          <AnswerCard answer={SAMPLE_ANSWER} index={index} />

          <details className="group rounded-(--radius-surface) bg-(--color-bg) px-4 py-3">
            <summary className="cursor-pointer text-xs font-semibold text-(--color-accent-2-900)">
              Why this match — 7 criteria
            </summary>
            <ul className="m-0 mt-3 flex list-none flex-col gap-2.5 p-0">
              {SAMPLE_CRITERIA.map((c) => (
                <li key={c.label} className="flex gap-3 text-sm">
                  <span
                    className={
                      "w-12 flex-none font-semibold " +
                      (c.score === c.max ? "text-(--color-accent-2-700)" : "text-(--color-accent-750)")
                    }
                  >
                    {c.score}/{c.max}
                  </span>
                  <span>
                    <strong>{c.label}</strong> <span className="muted">— {c.why}</span>
                  </span>
                </li>
              ))}
            </ul>
          </details>

          <div className="flex flex-col gap-2">
            <span className="eyebrow">Ask next</span>
            <div className="flex flex-wrap gap-2">
              {SAMPLE_FOLLOW_UPS.map((q) => (
                <button key={q} className="pill" onClick={() => ask(q)}>
                  {q} →
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="flex w-full max-w-215 flex-col gap-3" aria-labelledby="extras-heading">
        <h2 id="extras-heading" className="text-xl font-semibold">
          Signing in also opens
        </h2>
        <div className="grid gap-3.5 sm:grid-cols-3">
          {SIGNED_IN_EXTRAS.map((item) => (
            <div key={item.title} className="card" style={{ gap: 6 }}>
              <div className="card-title">{item.title}</div>
              <div className="card-body">{item.body}</div>
            </div>
          ))}
        </div>
      </section>

      <LoginForm
        open={signingIn}
        onOpenChange={setSigningIn}
        next={typeof window === "undefined" ? "/ask" : `${window.location.pathname}${window.location.search}`}
        onBeforeRedirect={() => savePendingQuestion(draft)}
      />
    </div>
  );
}
