"use client";

import { useEffect, useState } from "react";
import { ImportWorkspace } from "@/features/ingest/ImportWorkspace";
import { ProposalList } from "@/features/ingest/components/ProposalList";
import { ResearchedRecently } from "@/features/ingest/components/ResearchedRecently";
import { RunHistory } from "@/features/ingest/components/RunHistory";
import { SourceGroups } from "@/features/ingest/components/SourceGroups";
import { SourcePanel } from "@/features/ingest/components/SourcePanel";
import { WaitingForYou } from "@/features/ingest/components/WaitingForYou";
import type { ImportRun, ImportSource, QueueItem, ResearchRecord, SourceProposal } from "@/features/ingest/lib/types";
import { authHeaders } from "@/lib/api/auth-headers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

type Panels = {
  sources: ImportSource[];
  runs: ImportRun[];
  queue: QueueItem[];
  proposals: SourceProposal[];
  research: ResearchRecord[];
};

class StaffOnlyError extends Error {}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { headers: await authHeaders(), cache: "no-store" });
  if (res.status === 403) throw new StaffOnlyError();
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

/**
 * Sangam Import, inside the Ask workspace: a guided Start → Working → Review → Done, with what is
 * waiting and what was researched under the Start step. Panels load when the view opens.
 */
export function ImportView() {
  const [panels, setPanels] = useState<Panels | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [staffOnly, setStaffOnly] = useState(false);
  // A new id is a new thread: a stopped or paused run is left behind, saved research is not.
  const [threadId, setThreadId] = useState(() => `import-${crypto.randomUUID()}`);

  useEffect(() => {
    let live = true;
    Promise.all([
      get<ImportSource[]>("/api/ingest/sources"),
      get<ImportRun[]>("/api/ingest/runs?limit=8"),
      get<QueueItem[]>("/api/ingest/queue?limit=20"),
      get<SourceProposal[]>("/api/ingest/proposals?limit=20"),
      get<ResearchRecord[]>("/api/ingest/research?limit=25"),
    ])
      .then(([sources, runs, queue, proposals, research]) => {
        if (live) setPanels({ sources, runs, queue, proposals, research });
      })
      .catch((e: unknown) => {
        if (!live) return;
        if (e instanceof StaffOnlyError) setStaffOnly(true);
        else setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      live = false;
    };
  }, []);

  if (staffOnly) {
    return (
      <div className="import-view">
        <div className="eyebrow">Tools · Import</div>
        <h2 className="import-title">Staff only</h2>
        <p className="muted measure import-lede">
          Sangam Import changes the catalog, so it is open to the Sangam team only. Ask Sangam is
          open to you.
        </p>
      </div>
    );
  }

  const start = (
    <>
      {error && <div className="import-error">Could not load what&apos;s waiting and what was researched: {error}</div>}
      {!panels && !error && <div className="muted">Loading…</div>}
      {panels && (
        <>
          <WaitingForYou items={panels.queue} sources={panels.sources} />
          <ResearchedRecently items={panels.research} />
          <SourceGroups sources={panels.sources} />
          <details className="import-section import-disclosure">
            <summary className="import-link">Details: runs, new websites and every source</summary>
            <div className="import-details">
              <RunHistory runs={panels.runs} />
              <ProposalList items={panels.proposals} />
              <SourcePanel sources={panels.sources} />
            </div>
          </details>
        </>
      )}
    </>
  );

  return (
    <div className="import-view import-view-open">
      <div className="import-intro">
        <span className="eyebrow">Import</span>
        <span className="import-hint">Bring new information into Sangam, with proof for every answer</span>
      </div>
      <ImportWorkspace
        key={threadId}
        threadId={threadId}
        onStartOver={() => setThreadId(`import-${crypto.randomUUID()}`)}
        start={start}
      />
    </div>
  );
}
