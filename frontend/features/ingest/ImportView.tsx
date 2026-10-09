"use client";

import { useEffect, useState } from "react";
import { ImportWorkspace } from "@/features/ingest/ImportWorkspace";
import { ProposalList } from "@/features/ingest/components/ProposalList";
import { ResearchedRecently } from "@/features/ingest/components/ResearchedRecently";
import { RunHistory } from "@/features/ingest/components/RunHistory";
import { SourceGroups } from "@/features/ingest/components/SourceGroups";
import { SourcePanel } from "@/features/ingest/components/SourcePanel";
import { WaitingForYou } from "@/features/ingest/components/WaitingForYou";
import { accessOf, type ImportAccess } from "@/features/ingest/lib/access";
import type { ImportRun, ImportSource, QueueItem, ResearchRecord, SourceProposal } from "@/features/ingest/lib/types";
import { authHeaders } from "@/lib/api/auth-headers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

type Panels = {
  access: ImportAccess;
  sources: ImportSource[];
  runs: ImportRun[];
  queue: QueueItem[];
  proposals: SourceProposal[];
  research: ResearchRecord[];
};

// Until /api/me answers, the one task open to everyone.
const FUNDERS_ONLY: ImportAccess = { staff: false, stewardOf: [] };

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { headers: await authHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

/** Staff get every panel; anyone else only what they researched, as the rest is the team's. */
async function loadPanels(): Promise<Panels> {
  const access = accessOf(await get<Parameters<typeof accessOf>[0]>("/api/me"));
  const research = get<ResearchRecord[]>("/api/ingest/research?limit=25");
  if (!access.staff) return { access, sources: [], runs: [], queue: [], proposals: [], research: await research };
  const [sources, runs, queue, proposals] = await Promise.all([
    get<ImportSource[]>("/api/ingest/sources"),
    get<ImportRun[]>("/api/ingest/runs?limit=8"),
    get<QueueItem[]>("/api/ingest/queue?limit=20"),
    get<SourceProposal[]>("/api/ingest/proposals?limit=20"),
  ]);
  return { access, sources, runs, queue, proposals, research: await research };
}

/**
 * One Import thread: a guided Start → Working → Review → Done, with what is waiting and what was
 * researched under the Start step. Panels load once, and stay while threads change.
 */
export function ImportView({
  threadId,
  resume,
  onStartOver,
  onFirstSend,
}: {
  threadId: string;
  /** Opened from the list, so its saved messages load. */
  resume: boolean;
  onStartOver: () => void;
  onFirstSend: (text: string) => void;
}) {
  const [panels, setPanels] = useState<Panels | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    loadPanels()
      .then((p) => {
        if (live) setPanels(p);
      })
      .catch((e: unknown) => {
        if (live) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      live = false;
    };
  }, []);

  const start = (
    <>
      {error && <div className="import-error">Could not load what&apos;s waiting and what was researched: {error}</div>}
      {!panels && !error && <div className="muted">Loading…</div>}
      {panels && (
        <>
          {panels.access.staff && <WaitingForYou items={panels.queue} sources={panels.sources} />}
          <ResearchedRecently items={panels.research} />
          {panels.access.staff && (
            <>
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
        resume={resume}
        onStartOver={onStartOver}
        onFirstSend={onFirstSend}
        start={start}
        access={panels?.access ?? FUNDERS_ONLY}
      />
    </div>
  );
}
