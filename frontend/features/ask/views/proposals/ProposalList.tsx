"use client";

import { useState } from "react";
import { BucketCards, FilterRow, ListMore, SearchBox, Tag, useShowMore } from "@/components/ui";
import { shortDate } from "@/lib/format";
import type { ProposalItem as Proposal } from "./api";
import { STEPS } from "./steps";

type Bucket = "all" | "progress" | "ready";
const DAY = 86_400_000;

const haystack = (p: Proposal) => [p.title, p.funder.name, p.org.name].join(" ").toLowerCase();

/* Every proposal the caller may read, newest first; Funder Match's "Proposals (N) →" lands here filtered. */
export function ProposalList({
  rows,
  initialFunder,
  onOpen,
  onFunderMatch,
}: {
  rows: Proposal[];
  initialFunder: number | null;
  onOpen: (id: number) => void;
  onFunderMatch: () => void;
}) {
  const [bucket, setBucket] = useState<Bucket>("all");
  const [funder, setFunder] = useState(initialFunder ? String(initialFunder) : "all");
  const [org, setOrg] = useState("all");
  const [started, setStarted] = useState({ value: "any", since: 0 });
  const [query, setQuery] = useState("");

  const q = query.trim().toLowerCase();
  const passes = (p: Proposal) =>
    (funder === "all" || String(p.funder.id) === funder) &&
    (org === "all" || p.org.slug === org) &&
    (started.value === "any" || Date.parse(p.created_at) >= started.since) &&
    (!q || haystack(p).includes(q));
  const narrowed = rows.filter(passes);
  const ready = (p: Proposal) => p.summary.ready;
  const shown = narrowed.filter((p) => bucket === "all" || (bucket === "ready") === ready(p));
  const [n, more] = useShowMore([bucket, funder, org, started.value, q].join("|"));

  const funders = [...new Map(rows.map((p) => [String(p.funder.id), p.funder.name]))].sort((a, b) =>
    a[1].localeCompare(b[1]),
  );
  const orgs = [...new Map(rows.map((p) => [p.org.slug, p.org.name]))].sort((a, b) => a[1].localeCompare(b[1]));

  if (rows.length === 0)
    return (
      <div className="card view-measure">
        <div className="card-title">No proposals yet</div>
        <div className="card-body">
          A proposal starts from a funder: open Funder Match, pick a funder and choose &ldquo;Start a proposal&rdquo;.
        </div>
        <button className="btn" type="button" onClick={onFunderMatch}>
          Open Funder Match →
        </button>
      </div>
    );

  return (
    <>
      <BucketCards<Bucket>
        items={[
          { key: "all", label: "All proposals", count: narrowed.length, sub: "Newest first" },
          { key: "progress", label: "In progress", count: narrowed.filter((p) => !ready(p)).length, sub: "Something still to do" },
          { key: "ready", label: "Ready", count: narrowed.filter(ready).length, sub: "Nothing left to fix" },
        ]}
        active={bucket}
        onPick={setBucket}
      />
      <FilterRow
        filters={[
          {
            key: "funder",
            label: "Funder",
            value: funder,
            defaultValue: "all",
            options: [["all", "All funders"], ...funders],
            onChange: setFunder,
          },
          ...(orgs.length > 1
            ? [{ key: "org", label: "Organisation", value: org, defaultValue: "all", options: [["all", "All organisations"], ...orgs] as [string, string][], onChange: setOrg }]
            : []),
          {
            key: "started",
            label: "Started",
            value: started.value,
            defaultValue: "any",
            options: [
              ["any", "Started any time"],
              ["30", "In the last 30 days"],
              ["90", "In the last 90 days"],
            ],
            onChange: (value: string) => setStarted({ value, since: Date.now() - Number(value) * DAY }),
          },
        ]}
      />
      <SearchBox value={query} onChange={setQuery} placeholder="Search proposals, funders and organisations…" />
      <p className="list-count">
        {shown.length} of {rows.length} proposals · newest first
      </p>

      {shown.length === 0 ? (
        <div className="muted">No proposals match these filters.</div>
      ) : (
        shown.slice(0, n).map((p) => {
          const sum = p.summary;
          return (
            <button key={p.id} type="button" className="pr-row" onClick={() => onOpen(p.id)}>
              <span className="pr-row-title">{p.title}</span>
              <span className="pr-row-side">
                <Tag tone={sum.ready ? "accent-2" : "outline"}>{sum.ready ? "Ready" : "In progress"}</Tag>
                <span className="pr-row-meta">Updated {shortDate(p.updated_at)}</span>
              </span>
              <span className="pr-row-meta">
                To {p.funder.name} · {p.org.name} · Step {sum.stage} of {STEPS.length}, {STEPS[sum.stage - 1]?.toLowerCase()} ·{" "}
                {sum.done} of {sum.total} parts done
                {p.fit_score !== null && ` · fit ${p.fit_score} / 100`}
              </span>
            </button>
          );
        })
      )}
      <ListMore shown={Math.min(n, shown.length)} total={shown.length} onMore={more} />
    </>
  );
}
