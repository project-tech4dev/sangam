"use client";

export function RfpWatchView() {
  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <div className="eyebrow">RFP watch</div>
        <h2 style={{ fontSize: 20 }}>Funding opportunities matched to the cohort</h2>
      </div>
      <div className="card" style={{ alignItems: "flex-start", gap: 10 }}>
        <div className="card-title">No calls tracked yet</div>
        <div className="card-body" style={{ maxWidth: 560 }}>
          The watcher hasn&apos;t run — no open calls or RFPs are recorded in the base. When
          opportunities land, each appears here with the cohort organisations it plausibly fits,
          scored against the funder&apos;s rubric, ready to open as a conversation.
        </div>
      </div>
    </div>
  );
}
