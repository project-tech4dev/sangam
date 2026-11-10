"use client";

import { useEffect, useState } from "react";
import { BucketCards, FilterRow, SearchBox } from "@/components/ui";
import { dayMonthYear } from "@/lib/format";
import type { MeOut } from "@/lib/api";
import { useOrgChoices } from "../lib/useOrgChoices";
import { CallCard, SOON_DAYS, daysLeft } from "./rfp-watch/CallCard";
import { type Feed, type FeedCall, getFeed, setStatus } from "./rfp-watch/api";

type Bucket = "foryou" | "soon" | "saved";

const EMPTY: Record<Bucket, string> = {
  foryou: "No open calls in your theme right now. New ones appear here after the next check.",
  soon: `Nothing closes in the next ${SOON_DAYS} days.`,
  saved: "Save a call to keep it here, even after its deadline passes.",
};

const haystack = (c: FeedCall) => [c.title, c.funder_name ?? "", ...c.themes].join(" ").toLowerCase();
const isOpen = (c: FeedCall) => c.call_status === "open" && (daysLeft(c.deadline) ?? -1) >= 0;

/* Open calls from funders Sangam knows that share a domain with the organisation; members save or hide them. */
export function RfpWatchView({
  orgs,
  onAsk,
  onFunderMatch,
  me: seed = null,
}: {
  orgs: { id: number; slug: string; name: string }[];
  onAsk: (question: string) => void;
  onFunderMatch: () => void;
  me?: MeOut | null;
}) {
  const [orgSlug, setOrgSlug] = useState("");
  const [feed, setFeed] = useState<Feed | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [bucket, setBucket] = useState<Bucket>("foryou");
  const [theme, setTheme] = useState("all");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<number | null>(null);

  const { me, choices, problem: meProblem } = useOrgChoices(orgs, seed);
  const active = orgSlug || choices[0]?.slug || "";

  useEffect(() => {
    if (!active) return;
    getFeed(active).then(
      (next) => {
        setProblem(null);
        setFeed(next);
      },
      (error: Error) => setProblem(error.message),
    );
  }, [active]);

  function pick(slug: string) {
    setFeed(null);
    setBucket("foryou");
    setTheme("all");
    setQuery("");
    setOrgSlug(slug);
  }

  async function change(c: FeedCall, status: "flagged" | "saved" | "dismissed") {
    if (!feed) return;
    setBusy(c.rfp_id);
    setProblem(null);
    try {
      await setStatus(c.rfp_id, feed.org_id, status);
      // A dismissed call leaves the feed; an unsaved closed one too, as the server would drop it.
      const keep = status !== "dismissed" && (status === "saved" || isOpen(c));
      setFeed({
        ...feed,
        items: keep ? feed.items.map((i) => (i.rfp_id === c.rfp_id ? { ...i, status } : i)) : feed.items.filter((i) => i.rfp_id !== c.rfp_id),
      });
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "That change was not saved.");
    } finally {
      setBusy(null);
    }
  }

  function ask(c: FeedCall) {
    const due = c.deadline ? `, ${isOpen(c) ? "due" : "which closed"} ${dayMonthYear(c.deadline)}` : "";
    onAsk(`Help me decide whether ${feed?.org_name} should apply to ${c.funder_name ?? "this funder"}'s call "${c.title}"${due}.`);
  }

  const all = feed?.items ?? [];
  const open = all.filter(isOpen);
  const themes = [...new Set(all.flatMap((c) => c.themes))].sort();
  const q = query.trim().toLowerCase();
  const passes = (c: FeedCall) => (theme === "all" || c.themes.includes(theme)) && (!q || haystack(c).includes(q));
  const lists: Record<Bucket, FeedCall[]> = {
    foryou: open.filter(passes),
    soon: open.filter((c) => (daysLeft(c.deadline) ?? Infinity) <= SOON_DAYS).filter(passes),
    saved: all.filter((c) => c.status === "saved").filter(passes),
  };
  const shown = lists[bucket];
  const stewarded = me?.memberships.filter((m) => m.role === "steward").length ?? 0;

  return (
    <div className="view">
      <div className="fm-head">
        <div className="fm-head-text">
          <div className="eyebrow">Use Cases</div>
          <h2 className="view-title">RFP Watch</h2>
          {feed && feed.domains.length > 0 && (
            <p className="rfp-sub">
              Calls from funders on Sangam whose theme matches {feed.org_name}: <strong>{feed.domains.join(", ")}</strong>.
              {feed.last_pulled && ` Last checked ${dayMonthYear(feed.last_pulled)}.`}
            </p>
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
          <div className="card-title">RFP Watch works for an organisation</div>
          <div className="card-body">
            You are signed in but not a member of an organisation yet. Ask your organisation&apos;s admin to add you, or ask
            Sangam staff. Once you belong to one, open calls in its theme appear here.
          </div>
        </div>
      ) : !feed ? (
        !problem && <div className="muted">Loading…</div>
      ) : feed.domains.length === 0 ? (
        <div className="card view-measure rfp-empty">
          <div className="card-title">Tell us what {feed.org_name} works on</div>
          <div className="card-body">
            We show a call only when its theme matches yours, such as Education, Health or Livelihoods. This profile has no
            theme yet, so no call can be matched to it. Sangam staff or the organisation&apos;s stewards can add them by researching it in Sangam Scout.
          </div>
        </div>
      ) : (
        <>
          <BucketCards<Bucket>
            label="Which calls"
            items={[
              { key: "foryou", label: "For you", count: lists.foryou.length, sub: "Open calls in your theme" },
              { key: "soon", label: "Closing soon", count: lists.soon.length, sub: `Due in the next ${SOON_DAYS} days` },
              { key: "saved", label: "Saved", count: lists.saved.length, sub: "Calls you are considering" },
            ]}
            active={bucket}
            onPick={setBucket}
          />
          <div className="rfp-tools">
            <SearchBox value={query} onChange={setQuery} placeholder="Search calls or funders" />
            {themes.length > 1 && (
              <FilterRow
                filters={[
                  {
                    key: "theme",
                    label: "Theme",
                    value: theme,
                    defaultValue: "all",
                    options: [["all", "All themes"], ...themes.map((t): [string, string] => [t, t])],
                    onChange: setTheme,
                  },
                ]}
              />
            )}
          </div>
          <p className="list-count">
            {shown.length} {shown.length === 1 ? "call" : "calls"}, soonest deadline first
          </p>

          {shown.length === 0 ? (
            open.length === 0 && bucket === "foryou" && !q && theme === "all" ? (
              <div className="card view-measure rfp-empty">
                <div className="card-title">No open calls in {feed.domains.join(", ")} right now</div>
                <div className="card-body">
                  {feed.last_pulled ? `Sangam last checked funders' pages on ${dayMonthYear(feed.last_pulled)}. ` : ""}
                  Most CSR money is given without an open call, so funders who have backed work like yours are still worth a
                  look.
                </div>
                <div>
                  <button type="button" className="btn btn-primary" onClick={onFunderMatch}>
                    See funders who fit you
                  </button>
                </div>
              </div>
            ) : (
              <div className="muted">{q || theme !== "all" ? "No calls match this search." : EMPTY[bucket]}</div>
            )
          ) : (
            <div className="rfp-list">
              {shown.map((c) => (
                <CallCard
                  key={c.rfp_id}
                  call={c}
                  canAct={feed.can_act}
                  orgName={feed.org_name}
                  busy={busy === c.rfp_id}
                  onStatus={(status) => change(c, status)}
                  onAsk={() => ask(c)}
                />
              ))}
            </div>
          )}

          <p className="rfp-foot muted">
            Not seeing a call you expected? Sangam only watches funders it already knows.{" "}
            <button type="button" className="rfp-inline-link" onClick={onFunderMatch}>
              Try Funder Match
            </button>{" "}
            for funders who fit you but have no open call.
          </p>
        </>
      )}
    </div>
  );
}
