"use client";

import { useState } from "react";
import type { Fact, Proposal } from "./api";

type Save = (set: Record<string, unknown>) => Promise<void>;

// A marker's kind in words; the marker itself never reaches the screen.
const RECORD: Record<string, string> = {
  org: "Sangam's record of your organisation",
  activity: "Sangam's record of a past grant",
  score: "Funder Match",
};

function standing(f: Fact): string {
  if (f.origin === "you_said") return `${f.said_by?.name ?? "Your team"} said this`;
  if (f.status === "confirmed") return "✓ Confirmed";
  return {
    registry: "✓ From Sangam's record",
    vault: "✓ From your document",
    web: "! From the web, not checked",
    derived: "! Worked out by Sangam, not checked",
  }[f.origin];
}

function source(f: Fact): string | null {
  const kind = f.marker?.match(/^\[(\w+):/)?.[1];
  const name = f.source_name || (kind ? RECORD[kind] : null);
  return name ? `${name}${f.page ? `, page ${f.page}` : ""}` : null;
}

/** The facts Sangam Pitch keeps for one part: each with its standing and source in words, and the person's say. */
export function FactList({ proposal, part, save }: { proposal: Proposal; part: string; save: Save }) {
  const canEdit = proposal.can_edit;
  const all = Object.entries(proposal.work.facts ?? {}).filter(([, f]) => f.section === part);
  const live = all.filter(([, f]) => f.status === "proposed" || f.status === "confirmed");
  const setAside = all.length - live.length;
  const [fixing, setFixing] = useState<{ key: string; value: string } | null>(null);

  if (live.length === 0)
    return <p className="muted pr-facts-empty">No facts for this part yet. Ask Sangam Pitch what it holds.</p>;

  return (
    <ul className="pr-facts" aria-label="Facts for this part">
      {live.map(([key, f]) => (
        <li key={key} className="pr-fact" data-tier={f.status === "confirmed" && f.origin !== "you_said" ? "confirmed" : f.tier}>
          <div className="pr-fact-line">
            <span className="pr-fact-subject">{f.subject}</span>
            <strong>{f.value}</strong>
            {f.as_of && <span className="muted">{f.as_of}</span>}
          </div>
          <div className="pr-fact-standing">
            {standing(f)}
            {source(f) && <span className="muted"> · {source(f)}</span>}
          </div>
          {canEdit && f.status === "proposed" && fixing?.key !== key && (
            <div className="pr-fact-actions">
              <button className="btn btn-ghost" type="button" onClick={() => save({ [`facts.${key}.status`]: "confirmed" })}>
                Yes, it&apos;s right
              </button>
              <button className="btn btn-ghost" type="button" onClick={() => setFixing({ key, value: f.value })}>
                No, change it
              </button>
              <button className="btn btn-ghost" type="button" onClick={() => save({ [`facts.${key}.status`]: "rejected" })}>
                Don&apos;t use it
              </button>
            </div>
          )}
          {fixing?.key === key && (
            <form
              className="pr-fact-actions"
              onSubmit={(e) => {
                e.preventDefault();
                if (!fixing.value.trim()) return;
                void save({ [`facts.${key}.correct`]: fixing.value.trim() }).then(() => setFixing(null));
              }}
            >
              <input
                className="input"
                value={fixing.value}
                onChange={(e) => setFixing({ key, value: e.target.value })}
                aria-label={`The right value for ${f.subject}`}
                autoFocus
              />
              <button className="btn" type="submit" disabled={!fixing.value.trim()}>
                Save
              </button>
              <button className="btn btn-ghost" type="button" onClick={() => setFixing(null)}>
                Cancel
              </button>
            </form>
          )}
        </li>
      ))}
      {setAside > 0 && (
        <li className="muted pr-facts-empty">
          {setAside} {setAside === 1 ? "fact" : "facts"} set aside or replaced.
        </li>
      )}
    </ul>
  );
}
