"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import type { MatchList, MatchTier, MeOut } from "@/lib/api";
import { getMatches, getMe, runMatch } from "./funder-match/api";
import { MatchCard, shortDate, TIER_LABEL } from "./funder-match/MatchCard";

type Org = { slug: string; name: string };
type Filter = "all" | "strong" | "medium";

/* Every funder ranked for one organisation from its latest saved run; staff, stewards and admins can rerun it. */
export function FunderMatchView({ orgs }: { orgs: { id: number; slug: string; name: string }[] }) {
  const [me, setMe] = useState<MeOut | null>(null);
  const [orgSlug, setOrgSlug] = useState("");
  const [list, setList] = useState<MatchList | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [running, setRunning] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  // Staff pick from every organisation; everyone else from the ones they belong to.
  const choices: Org[] = useMemo(() => {
    if (!me) return [];
    if (me.is_staff) return orgs.map(({ slug, name }) => ({ slug, name }));
    return me.memberships.map((m) => ({ slug: m.org_slug, name: m.org_name }));
  }, [me, orgs]);

  useEffect(() => {
    getMe().then(setMe, (error: Error) => setProblem(error.message));
  }, []);

  // The first organisation until one is picked.
  const active = orgSlug || choices[0]?.slug || "";

  useEffect(() => {
    if (!active) return;
    getMatches(active).then(
      (next) => {
        setProblem(null);
        setList(next);
      },
      (error: Error) => setProblem(error.message),
    );
  }, [active, reload]);

  function pick(slug: string) {
    setList(null);
    setSaved(null);
    setFilter("all");
    setOrgSlug(slug);
  }

  async function rerun() {
    setRunning(true);
    setProblem(null);
    setSaved(null);
    try {
      const run = await runMatch(active);
      const t = run.tiers;
      setSaved(`Saved · ${run.funders_checked} funders checked · ${t.strong} strong, ${t.medium} medium`);
      setReload((n) => n + 1);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "The run was not saved.");
    } finally {
      setRunning(false);
    }
  }

  const ranked = (list?.matches ?? []).filter((m) => m.tier === "strong" || m.tier === "medium");
  const shown = filter === "all" ? ranked : ranked.filter((m) => m.tier === filter);
  const folded = (list?.matches ?? []).filter((m) => m.tier === "weak" || m.tier === "not_scored");
  const run = list?.run ?? null;

  return (
    <div className="view">
      <div className="fm-head">
        <div className="fm-head-text">
          <div className="eyebrow">Use Cases</div>
          <h2 className="view-title">Funder Match</h2>
          {list && (
            <div className="fm-run-line">
              <span>
                {run
                  ? `Latest run ${shortDate(run.run_at)} · ${run.funders_checked} funders checked · ${
                      run.earlier_runs ? `${run.earlier_runs} earlier run${run.earlier_runs > 1 ? "s" : ""}` : "first run"
                    }`
                  : "Not run yet"}
              </span>
              {list.may_run && (
                <button className="btn btn-ghost fm-rerun" type="button" onClick={rerun} disabled={running}>
                  <RefreshCw className="icon icon-sm" />
                  {running ? "Running…" : run ? "Rerun match" : "Run the first match"}
                </button>
              )}
              {saved && (
                <span className="fm-saved" role="status" aria-live="polite">
                  {saved}
                </span>
              )}
            </div>
          )}
        </div>
        {choices.length === 1 ? (
          <div className="fm-org-pick">
            <span className="eyebrow">Your organisation</span>
            <span className="fm-org-fixed">{choices[0].name}</span>
          </div>
        ) : choices.length > 1 ? (
          <label className="fm-org-pick">
            <span className="eyebrow">{me?.is_staff ? "Organisation · staff" : "Organisation"}</span>
            <select className="input" value={active} onChange={(event) => pick(event.target.value)}>
              {choices.map((org) => (
                <option key={org.slug} value={org.slug}>
                  {org.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>

      {problem && <p className="import-error" role="alert">{problem}</p>}

      {me && choices.length === 0 ? (
        <div className="card view-measure">
          <div className="card-title">Funder Match works for an organisation</div>
          <div className="card-body">
            You are signed in but not a member of an organisation yet. Ask your organisation&apos;s admin to add you, or
            ask Sangam staff. Once you belong to one, its matches appear here.
          </div>
        </div>
      ) : !list ? (
        !problem && <div className="muted">Loading…</div>
      ) : !run ? (
        <div className="card view-measure">
          <div className="card-title">No match saved for {list.org.name} yet</div>
          <div className="card-body">
            {list.may_run
              ? "Run the first match to score every funder in the base against this organisation."
              : "Its stewards, admins or Sangam staff can run the first match."}
          </div>
        </div>
      ) : (
        <>
          <div className="fm-stats" role="group" aria-label="Summary">
            {(["strong", "medium"] as const).map((t) => (
              <button
                key={t}
                type="button"
                className="fm-stat"
                data-active={filter === t}
                onClick={() => setFilter(filter === t ? "all" : t)}
              >
                <span className="fm-stat-num">{list.counts[t]}</span>
                <span className="fm-stat-label">{TIER_LABEL[t]}s</span>
                <span className="muted fm-meta">{t === "strong" ? "Score 75 or more" : "Score 55–74"}</span>
              </button>
            ))}
            <div className="fm-stat">
              <span className="fm-stat-num">{run.funders_checked}</span>
              <span className="fm-stat-label">Funders checked</span>
              <span className="muted fm-meta">Every funder in the base</span>
            </div>
          </div>

          <div className="fm-filters" role="group" aria-label="Show">
            {(["all", "strong", "medium"] as Filter[]).map((f) => (
              <button key={f} type="button" className="pill" data-active={filter === f} onClick={() => setFilter(f)}>
                {f === "all" ? "All fits" : TIER_LABEL[f as MatchTier]}
              </button>
            ))}
            <span className="muted fm-meta">Ranked by fit score, highest first</span>
          </div>

          {shown.length === 0 ? (
            <div className="muted">No {filter === "all" ? "strong or medium" : filter} fits in this run.</div>
          ) : (
            shown.map((m) => <MatchCard key={m.id} match={m} rank={ranked.indexOf(m) + 1} />)
          )}

          {folded.length > 0 && (
            <details className="import-disclosure fm-weak">
              <summary>Weak or no fit · {folded.length}</summary>
              <div className="fm-weak-list">
                {folded.map((m) => (
                  <div key={m.id} className="fm-weak-row">
                    <span className="fm-weak-name">{m.funder.name}</span>
                    <span className="muted">{m.score === null ? "Not scored" : `${m.score} / 100`}</span>
                    <span className="muted">{m.card.reasons.find((r) => r.kind === "gap")?.text ?? ""}</span>
                  </div>
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </div>
  );
}
