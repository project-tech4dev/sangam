"use client";

import { useEffect, useState } from "react";
import { ScoutChat } from "@/features/ingest/ScoutChat";
import { ProposalList } from "@/features/ingest/components/ProposalList";
import { ResearchedRecently } from "@/features/ingest/components/ResearchedRecently";
import { RunHistory } from "@/features/ingest/components/RunHistory";
import { SourceGroups } from "@/features/ingest/components/SourceGroups";
import { SourcePanel } from "@/features/ingest/components/SourcePanel";
import { accessOf, type ImportAccess, type VaultFile } from "@/features/ingest/lib/access";
import type {
  ImportOverview,
  ImportRun,
  ImportSource,
  QueueItem,
  ResearchRecord,
  SourceProposal,
} from "@/features/ingest/lib/types";
import { authHeaders } from "@/lib/api/auth-headers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

type Panels = {
  access: ImportAccess;
  vaultFiles: VaultFile[];
  sources: ImportSource[];
  runs: ImportRun[];
  queue: QueueItem[];
  proposals: SourceProposal[];
  research: ResearchRecord[];
};

// Until the overview answers, the one task open to everyone.
const FUNDERS_ONLY: ImportAccess = { staff: false, stewardOf: [], orgs: [] };

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { headers: await authHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

/** One request: each separate call could land on a backend instance that is still starting. */
async function loadPanels(): Promise<Panels> {
  const o = await get<ImportOverview>("/api/ingest/overview");
  const vaultFiles: VaultFile[] = o.vault.map((v) => ({
    id: v.id, title: v.title, doc_type: v.doc_type, org: v.org, orgId: v.org_id, orgName: v.org_name,
  }));
  const { sources, runs, queue, proposals, research } = o;
  return { access: accessOf(o.me), vaultFiles, sources, runs, queue, proposals, research };
}

/** One Scout thread, with what was researched under the empty composer. Panels load once, and stay while threads change. */
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

  // After an undo or a delete, only the list changes.
  async function reloadResearch() {
    const research = await get<ResearchRecord[]>("/api/ingest/research?limit=25").catch(() => null);
    if (research) setPanels((p) => (p ? { ...p, research } : p));
  }

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

  const below = (
    <>
      {error && <div className="import-error">Could not load what was researched: {error}</div>}
      {panels && (
        <>
          <ResearchedRecently items={panels.research} staff={panels.access.staff} onChanged={reloadResearch} />
          {panels.access.staff && (
            <details className="import-section import-disclosure">
              <summary className="import-link">Team tools</summary>
              <div className="import-details">
                <SourceGroups sources={panels.sources} />
                <SourcePanel sources={panels.sources} />
                <RunHistory runs={panels.runs} />
                <ProposalList items={panels.proposals} />
              </div>
            </details>
          )}
        </>
      )}
    </>
  );

  return (
    <ScoutChat
      key={threadId}
      threadId={threadId}
      resume={resume}
      onStartOver={onStartOver}
      onFirstSend={onFirstSend}
      below={below}
      access={panels?.access ?? FUNDERS_ONLY}
      vaultFiles={panels?.vaultFiles}
      staff={panels?.access.staff ? panels : null}
    />
  );
}
