"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { BucketCards, FilterRow, SearchBox } from "@/components/ui";
import type { MatchList, MatchRow, MeOut } from "@/lib/api";
import { useOrgChoices } from "../lib/useOrgChoices";
import { getMatches, runMatch } from "./funder-match/api";
import { funderTypeGroup, funderTypeLabel } from "./funder-match/funderType";
import { shortDate } from "@/lib/format";
import { setUrlParams } from "@/lib/url";
import { MatchCard, type ProposalNav } from "./funder-match/MatchCard";
import { useProposals } from "./proposals/api";
import { COMING_SOON } from "../lib/comingSoon";

type Bucket = "all" | "strong" | "medium";

// What search reads: the funder's name and type, and every reason on its card.
const haystack = (m: MatchRow) =>
  [m.funder.name, funderTypeLabel(m.funder.funder_type), ...m.card.reasons.map((r) => r.text)].join(" ").toLowerCase();

/* Every funder ranked for one organisation from its latest saved run; staff, stewards and admins can rerun it. */
export function FunderMatchView({
  orgs,
  nav,
  me: seed = null,
}: {
  orgs: { id: number; slug: string; name: string }[];
  nav: ProposalNav;
  me?: MeOut | null;
}) {
  // In the address, so Back from a proposal opened here returns to the same organisation.
  const orgParam = useSearchParams().get("org") ?? "";
  const [list, setList] = useState<MatchList | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [bucket, setBucket] = useState<Bucket>("all");
  const [type, setType] = useState("all");
  const [proposal, setProposal] = useState("any");
  const [query, setQuery] = useState("");
  const [running, setRunning] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  const { me, choices, problem: meProblem } = useOrgChoices(orgs, seed);

  // The first organisation until one is picked; a slug from the address counts only if it is one of yours.
  const orgSlug = choices.some((c) => c.slug === orgParam) ? orgParam : "";
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
    setBucket("all");
    setType("all");
    setProposal("any");
    setQuery("");
    setUrlParams({ org: slug }, "replace");
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

  const proposals = useProposals();
  const started = new Set(proposals.filter((p) => p.org.slug === list?.org.slug).map((p) => p.funder.id));
  const all = list?.matches ?? [];
  const ranked = all.filter((m) => m.tier === "strong" || m.tier === "medium");
  const folded = all.filter((m) => m.tier === "weak" || m.tier === "not_scored");
  const q = query.trim().toLowerCase();
  // The dropdown and the search narrow every bucket; the bucket picks the tier.
  const passes = (m: MatchRow) =>
    (type === "all" || funderTypeGroup(m.funder.funder_type) === type) &&
    (proposal === "any" || (proposal === "has") === started.has(m.funder.id)) &&
    (!q || haystack(m).includes(q));
  const narrowed = ranked.filter(passes);
  const shown = bucket === "all" ? narrowed : narrowed.filter((m) => m.tier === bucket);
  const atDefault = bucket === "all" && type === "all" && proposal === "any" && !q;
  const types = [...new Set(all.map((m) => funderTypeGroup(m.funder.funder_type)))].sort();
  const stewarded = me?.memberships.filter((m) => m.role === "steward").length ?? 0;
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
            <span className="eyebrow">
              {me?.is_staff ? "Organisation · all" : stewarded > 1 ? `Organisation · ${stewarded} you steward` : "Organisation"}
            </span>
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

      {(problem ?? meProblem) && <p className="import-error" role="alert">{problem ?? meProblem}</p>}

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
          <BucketCards<Bucket>
            items={[
              { key: "all", label: "All fits", count: narrowed.length, sub: "Ranked by fit score" },
              { key: "strong", label: "Strong", count: narrowed.filter((m) => m.tier === "strong").length, sub: "Score 75 or more" },
              { key: "medium", label: "Medium", count: narrowed.filter((m) => m.tier === "medium").length, sub: "Score 55–74" },
            ]}
            active={bucket}
            onPick={setBucket}
          />
          <FilterRow
            filters={[
              {
                key: "type",
                label: "Funder type",
                value: type,
                defaultValue: "all",
                options: [["all", "All funder types"], ...types.map((t): [string, string] => [t, t])],
                onChange: setType,
              },
              ...(COMING_SOON.has("proposals")
                ? []
                : [
                    {
                      key: "proposal",
                      label: "Proposal",
                      value: proposal,
                      defaultValue: "any",
                      options: [
                        ["any", "Any proposal status"],
                        ["has", "Has a proposal"],
                        ["none", "No proposal yet"],
                      ] as [string, string][],
                      onChange: setProposal,
                    },
                  ]),
            ]}
          />
          <SearchBox value={query} onChange={setQuery} placeholder="Search funders and reasons…" />
          <p className="list-count">
            {shown.length} of {ranked.length} scored funders · ranked by fit score, highest first
          </p>

          {shown.length === 0 ? (
            <div className="muted">No funders match these filters for {list.org.name}.</div>
          ) : (
            shown.map((m) => <MatchCard key={m.id} match={m} rank={ranked.indexOf(m) + 1} org={list.org} nav={nav} mayStart={list.may_run} />)
          )}

          {atDefault && folded.length > 0 && (
            <details className="import-disclosure fm-weak">
              <summary>
                Weak or no fit · {folded.length} scored below 55 or checked with nothing in common
              </summary>
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
