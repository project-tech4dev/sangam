"use client";

import { useState } from "react";
import { BucketCards, FilterRow, ListMore, SearchBox, useCursorList, type Filter } from "@/components/ui";
import type { MeOut, Story, StoryEntity, StoryPage } from "@/lib/api";
import { shortDate } from "@/lib/format";
import { call } from "../../lib/rest";
import { useOrgChoices } from "../../lib/useOrgChoices";
import { StoryCard, TOPIC_LABEL } from "./StoryCard";

type BucketKey = "org" | "funder" | "general";
const COUNT_CAP = 501;
const shown = (n: number | undefined) => (n === undefined ? "–" : n >= COUNT_CAP ? "500+" : n);

/* News about the caller's organisations, every watched funder, and the sector: three buckets, one list. */
export function MediaView({ orgs, me: seed = null }: { orgs: { slug: string; name: string }[]; me?: MeOut | null }) {
  const { me, choices, problem } = useOrgChoices(orgs, seed);
  const [bucket, setBucket] = useState<BucketKey>("org");
  const [entity, setEntity] = useState("all");
  const [area, setArea] = useState<string | null>(null);
  const [topic, setTopic] = useState("all");
  const [sentiment, setSentiment] = useState("all");
  const [source, setSource] = useState("all");
  const [since, setSince] = useState("30d");
  const [query, setQuery] = useState("");

  const hasOrgs = (me?.memberships.length ?? 0) > 0;
  const areaDefault = me?.is_staff || !hasOrgs ? "all" : "mine";
  const areaNow = area ?? areaDefault;
  // Area is sent on every bucket, so General's card counts the same area its list shows.
  const params = new URLSearchParams({ bucket, since, limit: "10", area: areaNow });
  if (bucket === "general") {
    if (topic !== "all") params.set("topic", topic);
  } else if (entity !== "all") params.set(bucket, entity);
  if (sentiment !== "all") params.set("sentiment", sentiment);
  if (source !== "all") params.set("source", source);
  if (query.trim()) params.set("q", query.trim());
  const ready = me !== null && !(bucket === "org" && !hasOrgs && !me.is_staff);

  const list = useCursorList<Story, StoryPage>(
    ready ? params.toString() : "",
    (cursor) =>
      ready
        ? call<StoryPage>(`/api/news/stories?${params}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`)
        : Promise.resolve({ items: [], next_cursor: null, counts: null, last_pull: null }),
    (s) => s.row_id,
  );
  const counts = list.last?.counts ?? null;
  const lastPull = list.last?.last_pull ?? null;
  // Funders seen so far in this list; the picker's choices grow as it scrolls.
  const funders = [...new Map(list.items.flatMap((s) => (s.about?.kind === "funder" ? [[s.about.slug, s.about.name]] : [])) as [string, string][])]
    .sort((a, b) => a[1].localeCompare(b[1]));

  function pick(next: BucketKey) {
    setBucket(next);
    setEntity("all");
  }

  async function hide(story: Story, e: StoryEntity) {
    await call(`/api/news/stories/${story.id}/hide`, "POST", e.kind === "org" ? { org_id: e.id } : { funder_id: e.id });
    list.remove((s) => s.row_id !== story.row_id);
  }

  const filters: Filter[] = [];
  if (bucket === "general") {
    filters.push({
      key: "area", label: "Area", value: areaNow, defaultValue: areaDefault, onChange: setArea,
      options: [...(hasOrgs ? [["mine", "My area"] as [string, string]] : []), ["north_east", "All North East"], ["all", "Everywhere"]],
    });
    filters.push({
      key: "topic", label: "Topic", value: topic, defaultValue: "all", onChange: setTopic,
      options: [["all", "All topics"], ...["fcra", "csr_funding", "ngo_news"].map((t): [string, string] => [t, TOPIC_LABEL[t]])],
    });
  } else {
    const named = bucket === "org" ? choices.map((c) => [c.slug, c.name]) : funders;
    if (named.length > 1 || entity !== "all")
      filters.push({
        key: "entity", label: bucket === "org" ? "Organisation" : "Funder", value: entity, defaultValue: "all", onChange: setEntity,
        options: [["all", bucket === "org" ? "All your organisations" : "All funders"], ...named.map(([s, n]): [string, string] => [s, n])],
      });
  }
  filters.push(
    {
      key: "sentiment", label: "Sentiment", value: sentiment, defaultValue: "all", onChange: setSentiment,
      options: [["all", "Any sentiment"], ["positive", "Positive"], ["neutral", "Neutral"], ["negative", "Negative"]],
    },
    {
      key: "source", label: "Source", value: source, defaultValue: "all", onChange: setSource,
      options: [["all", "All sources"], ["news", "News"], ["social", "Social"], ["web", "Other web"]],
    },
    {
      key: "since", label: "When", value: since, defaultValue: "30d", onChange: setSince,
      options: [["30d", "Last 30 days"], ["all", "Any date"]],
    },
  );

  const mine = me?.is_staff ? "Every cohort organisation" : hasOrgs ? me!.memberships.map((m) => m.org_name).join(", ") : "No organisation linked";
  const total = counts?.[bucket] ?? 0;
  return (
    <div className="view">
      <div className="fm-head-text">
        <div className="eyebrow">Use Cases</div>
        <h2 className="view-title">Media &amp; Signals</h2>
        <div className="fm-run-line">
          {lastPull ? `Last pull ${shortDate(lastPull)} · ` : "No news pulled yet · "}
          news, CSR media, LinkedIn, Instagram and X · one card per story, copies folded in
        </div>
      </div>
      <BucketCards<BucketKey>
        label="Bucket"
        active={bucket}
        onPick={pick}
        items={[
          { key: "org", label: "My organisations", count: shown(counts?.org), sub: mine },
          { key: "funder", label: "Funders", count: shown(counts?.funder), sub: "Every funder Sangam watches" },
          { key: "general", label: "General", count: shown(counts?.general), sub: "FCRA, CSR trends, NGO news" },
        ]}
      />
      <FilterRow filters={filters} />
      <SearchBox value={query} onChange={setQuery} placeholder="Search titles, summaries, outlets, places…" />
      {(problem ?? list.error) && <p className="import-error" role="alert">{problem ?? list.error}</p>}
      {me && bucket === "org" && !hasOrgs && !me.is_staff ? (
        <div className="card view-measure">
          <div className="card-title">No organisation linked to your account</div>
          <div className="card-body">
            Ask your organisation&apos;s admin to add you, and its news will collect here. Funders and General are open to
            everyone signed in.
          </div>
        </div>
      ) : (
        <>
          <p className="list-count">
            {shown(total)} {total === 1 ? "story" : "stories"}
            {query.trim() ? ` matching "${query.trim()}"` : ""} · strongest match first
          </p>
          {list.items.length === 0 && !list.busy && (
            <div className="muted">Nothing here with these filters. Try Any date, or clear the search.</div>
          )}
          {list.items.map((s) => (
            <StoryCard
              key={s.row_id}
              story={s}
              about={bucket === "general" ? undefined : bucket}
              onHide={me?.is_staff ? (e) => void hide(s, e) : undefined}
            />
          ))}
          <ListMore
            shown={list.items.length}
            total={list.more ? Math.max(total, list.items.length + 1) : list.items.length}
            onMore={() => list.more?.()}
            busy={list.busy}
          />
        </>
      )}
    </div>
  );
}
