"use client";

import { useState } from "react";
import { authHeaders } from "@/lib/api/auth-headers";
import type { ImportSource, QueueItem } from "../lib/types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

/** Names Sangam would not join on its own: one yes / no / not sure question each, with no scores. */
export function WaitingForYou({ items, sources }: { items: QueueItem[]; sources: ImportSource[] }) {
  const [gone, setGone] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  // A name with no close candidate has nothing to ask about.
  const asking = items.filter((q) => q.candidates.length > 0 && !gone.has(q.id));
  if (asking.length === 0) return null;
  const sourceName = (key: string | null) => sources.find((s) => s.key === key)?.name ?? "A source";

  async function answer(q: QueueItem, choice: "same" | "different" | "unsure") {
    setError(null);
    if (choice !== "unsure") {
      const failed = `Couldn't save your answer about “${q.raw_name}”. Try again.`;
      try {
        const res = await fetch(`${API}/api/ingest/queue/${q.id}`, {
          method: "POST",
          headers: { ...(await authHeaders()), "Content-Type": "application/json" },
          body: JSON.stringify({ answer: choice, candidate_id: q.candidates[0].id }),
        });
        if (!res.ok) return setError(failed);
      } catch {
        return setError(failed);
      }
    }
    setGone(new Set(gone).add(q.id));
  }

  return (
    <section className="import-section">
      <h2 className="import-h2">Waiting for you</h2>
      {error && <p className="import-error">{error}</p>}
      {asking.map((q) => (
        <div key={q.id} className="import-wait">
          <strong className="import-wait-title">
            Is “{q.raw_name}” the same as “{q.candidates[0].name}”?
          </strong>
          <span className="import-wait-text">
            {sourceName(q.source)} named it. The names are close but not the same, and joining two different
            organisations can&apos;t be undone — so Sangam asks.
          </span>
          <div className="import-wait-choices">
            <button type="button" className="pill" onClick={() => answer(q, "same")}>
              Yes, the same
            </button>
            <button type="button" className="pill" onClick={() => answer(q, "different")}>
              No, they&apos;re different
            </button>
            <button type="button" className="pill" onClick={() => answer(q, "unsure")}>
              Not sure
            </button>
          </div>
        </div>
      ))}
    </section>
  );
}
