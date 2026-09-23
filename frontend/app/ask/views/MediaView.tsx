"use client";

import { useEffect, useState } from "react";
import { Tag } from "../../components/ui";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

type NewsItem = {
  id: number;
  url: string;
  title: string | null;
  domain: string | null;
  seendate: string | null;
  topic: string | null;
};

const TOPIC_LABELS: Record<string, string> = {
  funders_grants: "Funders & grants",
  fcra_actions: "FCRA actions",
  fcra_policy: "FCRA policy",
  cso_ngo_activity: "CSO activity",
};

export function MediaView({ onDiscuss }: { onDiscuss: (seed: string) => void }) {
  const [items, setItems] = useState<NewsItem[] | null>(null);

  useEffect(() => {
    fetch(`${API}/api/news?limit=25`, { headers: { Authorization: "Bearer dev" } })
      .then((res) => res.json())
      .then((page) => setItems(page.items))
      .catch(() => setItems([]));
  }, []);

  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <div className="eyebrow">Media & signals</div>
        <h2 style={{ fontSize: 20 }}>Collected signals — all pending human review</h2>
        <p className="muted" style={{ margin: "4px 0 0", fontSize: 13 }}>
          Signals come from GDELT monitoring queries. None are auto-attached to organisations —
          linking is a manual vetting decision.
        </p>
      </div>
      {items === null ? (
        <div className="muted">Loading…</div>
      ) : items.length === 0 ? (
        <div className="card"><div className="card-body">No signals collected yet.</div></div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map((item) => (
            <div key={item.id} className="card" style={{ gap: 8, padding: 16 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <Tag tone="neutral">Pending review</Tag>
                {item.topic && <Tag tone="outline">{TOPIC_LABELS[item.topic] ?? item.topic}</Tag>}
                <span className="muted-2" style={{ fontSize: 11.5 }}>
                  {item.domain} · {item.seendate ? new Date(item.seendate).toLocaleDateString("en-IN") : "date unknown"}
                </span>
              </div>
              <a href={item.url} target="_blank" rel="noreferrer" style={{ fontSize: 13.5, fontWeight: 600 }}>
                {item.title ?? item.url}
              </a>
              <div>
                <button
                  className="btn btn-ghost"
                  style={{ padding: "2px 0", fontSize: 12.5 }}
                  onClick={() =>
                    onDiscuss(
                      `A news signal was collected: "${item.title ?? item.url}" (${item.domain}). Does this affect any organisation or funder in the base?`,
                    )
                  }
                >
                  Discuss in chat →
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
