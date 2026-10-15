"use client";

import type { Fact, Proposal } from "./api";
import { source } from "./FactList";

const CITE = /⟦(k\d+)⟧/g;
const PIECE = /((?:⟦k\d+⟧)+|\[Add:[^\]]*\])/;
const SCORE = ["Needs more", "Nearly there", "Strong"];

/** A section's draft as the funder would read it: each source a numbered mark, each gap in amber, no codes. */
export function WriteCard({ proposal, code }: { proposal: Proposal; code: string }) {
  const saved = proposal.work.sections[code] ?? {};
  const text = saved.text?.trim();
  if (!text) return null;
  const facts = proposal.work.facts ?? {};
  // Numbered by first use in this part, so the marks read 1, 2, 3 down the page.
  const order = [...new Set([...text.matchAll(CITE)].map((m) => m[1]))].filter((k) => facts[k]);
  const gaps = text.match(/\[Add:/g)?.length ?? 0;

  return (
    <div className="pr-draft">
      <div className="pr-draft-state">
        {saved.score != null && <span data-score={saved.score}>{SCORE[saved.score]}</span>}
        {saved.needs_rewrite && <span className="pr-draft-gaps">A fact it uses changed: needs rewriting</span>}
        {gaps > 0 && <span className="pr-draft-gaps">{gaps === 1 ? "1 gap to fill" : `${gaps} gaps to fill`}</span>}
      </div>
      {text.split(/\n\s*\n/).map((para, i) => (
        <p key={i} className="pr-draft-text">
          {para.split(PIECE).map((piece, j) => {
            if (piece.startsWith("⟦")) {
              // Sources side by side read as one mark: "1,2", not "12".
              const keys = [...piece.matchAll(CITE)].map((m) => m[1]).filter((k) => facts[k]);
              return keys.length === 0 ? null : (
                <sup key={j} className="pr-cite" title={keys.map((k) => label(facts[k])).join("\n")}>
                  {keys.map((k) => order.indexOf(k) + 1).join(",")}
                </sup>
              );
            }
            if (piece.startsWith("[Add:")) return <span key={j} className="pr-gap">{piece.slice(1, -1)}</span>;
            return piece;
          })}
        </p>
      ))}
      {order.length > 0 && (
        <ol className="pr-sources" aria-label="Sources">
          {order.map((k) => (
            <li key={k}>{label(facts[k])}</li>
          ))}
        </ol>
      )}
    </div>
  );
}

function label(f: Fact): string {
  const from = source(f) ?? (f.origin === "you_said" ? `${f.said_by?.name ?? "Your team"} said this` : null);
  return `${f.subject}: ${f.value}${from ? ` · ${from}` : ""}`;
}
