"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  fetchBaseline,
  fetchCheck,
  fetchChecks,
  runCheck,
  runState,
  statusOf,
  stepsOf,
  summaryOf,
  verdictOf,
  type Baseline,
  type CheckRun,
  type CheckRunDetail,
  type SourceCheck,
} from "../lib/changeCheck";
import { ApiError } from "@/lib/api/rest";
import { StepBar } from "./StepBar";

const STEPS = ["Baseline", "Compare", "Decide", "Review"];
const when = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
const host = (url: string) => url.replace(/^https?:\/\/(www\.)?/, "");

/** Which step the person is on: nothing checked yet, a decision to act on, or an update waiting in review. */
export function stepOf(run: CheckRunDetail | null): number {
  if (!run || !run.finished_at || run.error) return run ? 1 : 0;
  if (run.refresh_row_id) return 3;
  return verdictOf(run).next === "none" ? STEPS.length : 2;
}

/** One organisation's change check: what Sangam holds, what changed on each source, and what to do about it. */
export function ChangeCheck({ slug }: { slug: string }) {
  const [baseline, setBaseline] = useState<Baseline | null>(null);
  const [runs, setRuns] = useState<CheckRun[]>([]);
  const [run, setRun] = useState<CheckRunDetail | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([fetchBaseline(slug), fetchChecks(slug)])
      .then(async ([b, list]) => {
        const latest = list[0] ? await fetchCheck(list[0].run_id) : null;
        if (!live) return;
        setBaseline(b);
        setRuns(list);
        setRun(latest);
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [slug]);

  async function start(depth: "free" | "full", refresh: boolean, cost: string | null) {
    if (cost && !window.confirm(`This calls the AI model and costs ${cost}. Run it?`)) return;
    setBusy(refresh ? "Updating what changed…" : depth === "full" ? "Asking the judge…" : "Checking each source…");
    setError(null);
    try {
      setRun(await runCheck(slug, depth, refresh));
      setRuns(await fetchChecks(slug));
    } catch (e) {
      setError(e instanceof ApiError && e.status === 409
        ? "A check of this organisation is already running. Try again when it finishes."
        : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const verdict = run?.finished_at ? verdictOf(run) : null;
  return (
    <div className="page check-page">
      <Link href="/import" className="import-link">
        ← Scout
      </Link>
      <header className="import-head">
        <h1 className="import-h1">Check {baseline?.name ?? slug} for changes</h1>
        <p className="import-lede muted">
          Sangam fetches each source again and compares it with the copy the research read. Only what changed is
          updated, and nothing reaches the profile until you save it.
        </p>
      </header>
      <StepBar current={stepOf(run)} steps={STEPS} />
      {error && <p className="import-error">{error}</p>}

      <section className="import-section">
        <div className="import-section-head">
          <h2 className="import-h2">What Sangam holds</h2>
          <span className="import-hint">The version of each source the facts were read from.</span>
        </div>
        {baseline && baseline.sources.length === 0 ? (
          <p className="muted">
            No research of this organisation records which versions it read, so there is nothing to compare. Research
            it once in Scout first.
          </p>
        ) : (
          <div className="import-shelf">
            {baseline?.sources.map((s) => (
              <div key={s.url} className="check-row">
                <a href={s.url} target="_blank" rel="noreferrer" className="check-url">
                  {host(s.url)}
                </a>
                <span className="import-hint">
                  {s.kind === "document" ? "Document" : "Page"} · {s.facts} facts · read {s.read_on}
                  {s.archived ? " · copy kept" : " · no copy kept"}
                </span>
              </div>
            ))}
          </div>
        )}
        {baseline && baseline.unrecorded > 0 && (
          <p className="import-hint">
            {baseline.unrecorded} older research {baseline.unrecorded === 1 ? "row predates" : "rows predate"} saved
            copies; its sources are not checked.
          </p>
        )}
        <div className="check-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={!!busy || !baseline?.sources.length}
            onClick={() => start("free", false, null)}
          >
            Check for changes
          </button>
          <span className="import-hint">Free: no AI. Takes about a minute.</span>
        </div>
        {busy && (
          <p className="import-hint" role="status">
            {busy}
          </p>
        )}
      </section>

      {run && (
        <section className="import-section">
          <div className="import-section-head">
            <h2 className="import-h2">What changed</h2>
            <span className="import-hint">
              {run.depth === "full" ? "Full check" : "Free check"} · {when(run.started_at)}
              {run.requested_by && ` · by ${run.requested_by}`}
            </span>
          </div>
          {verdict && (
            <div className="import-wait">
              <strong className="import-wait-title">{verdict.title}</strong>
              {verdict.text && <p className="import-wait-text">{verdict.text}</p>}
              {run.checks.length > 0 && <p className="import-hint">{summaryOf(run)}</p>}
              <div className="import-wait-choices">
                {verdict.next === "judge" && (
                  <button type="button" className="btn btn-secondary" disabled={!!busy}
                    onClick={() => start("full", false, "a few cents")}>
                    Ask the judge · a few cents
                  </button>
                )}
                {verdict.next === "update" && (
                  <button type="button" className="btn btn-primary" disabled={!!busy}
                    onClick={() => start("full", true, "about $0.40")}>
                    Update what changed · about $0.40
                  </button>
                )}
                {verdict.next === "research" && (
                  <Link href="/import" className="btn btn-secondary">
                    Research again in Scout · about $2
                  </Link>
                )}
                {run.refresh_row_id && (
                  <Link href="/import" className="btn btn-primary">
                    Review &amp; save in Scout
                  </Link>
                )}
              </div>
            </div>
          )}
          <div className="import-shelf">
            {run.checks.map((c) => (
              <SourceResult key={c.url} check={c} depth={run.depth}
                facts={baseline?.sources.find((s) => s.url === c.url)?.facts ?? 0} />
            ))}
          </div>
        </section>
      )}

      {runs.length > 1 && (
        <section className="import-section">
          <h2 className="import-h2">Earlier checks</h2>
          <div className="import-shelf">
            {runs.map((r) => (
              <button
                key={r.run_id}
                type="button"
                className="check-row check-history"
                aria-current={r.run_id === run?.run_id ? "true" : undefined}
                onClick={async () => setRun(await fetchCheck(r.run_id))}
              >
                <span>{when(r.started_at)}</span>
                <span className="import-hint">
                  {r.depth === "full" ? "Full" : "Free"} · {runState(r)} ·{" "}
                  {r.sources} sources
                </span>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

/** One source's result; what changed, and each fact's verdict, open on demand. */
export function SourceResult({ check: c, depth = "free", facts = 0 }: {
  check: SourceCheck;
  depth?: "free" | "full";
  facts?: number;
}) {
  const state = statusOf(c.status);
  const line = (
    <span className="check-row-head">
      <span className={`tag ${state.tag}`}>{state.label}</span>
      <span className="check-url">{host(c.url)}</span>
    </span>
  );
  return (
    <details className="check-row import-disclosure">
      <summary>{line}</summary>
      <div className="check-body">
        <ol className="check-steps" aria-label="How this source was checked">
          {stepsOf(c, depth, facts).map((step) => (
            <li key={step.name} className="check-step" data-state={step.state}>
              <span className="check-step-name">{step.name}</span>
              <span className="check-step-text">{step.text}</span>
            </li>
          ))}
        </ol>
        {(c.removed_text.length > 0 || c.added_text.length > 0) && (
          <div className="check-diff">
            {c.removed_text.map((p, i) => (
              <p key={`r${i}`} className="check-diff-line" data-side="removed">
                − {p}
              </p>
            ))}
            {c.added_text.map((p, i) => (
              <p key={`a${i}`} className="check-diff-line" data-side="added">
                + {p}
              </p>
            ))}
          </div>
        )}
        {c.evidence && c.evidence.length > 0 && (
          <ul className="check-facts">
            {c.evidence.map((e, i) => (
              <li key={i} data-verdict={e.verdict}>
                <span className="check-fact-verdict">
                  {e.verdict === "intact" ? "✓ Still there" : e.verdict === "broken" ? "✗ Gone or changed" : "? Can't tell"}
                </span>{" "}
                {e.sentence}
              </li>
            ))}
          </ul>
        )}
      </div>
    </details>
  );
}
