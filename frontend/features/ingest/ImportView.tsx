"use client";

import { useEffect, useState } from "react";
import { ScoutChat } from "@/features/ingest/ScoutChat";
import { ProposalList } from "@/features/ingest/components/ProposalList";
import { ResearchedRecently } from "@/features/ingest/components/ResearchedRecently";
import { RunHistory } from "@/features/ingest/components/RunHistory";
import { SourceGroups } from "@/features/ingest/components/SourceGroups";
import { SourcePanel } from "@/features/ingest/components/SourcePanel";
import { accessOf, type ImportAccess, type VaultFile } from "@/features/ingest/lib/access";
import { vaultFilesOf } from "@/features/ingest/lib/vaultFiles";
import type { ImportRun, ImportSource, QueueItem, ResearchRecord, SourceProposal } from "@/features/ingest/lib/types";
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

// Until /api/me answers, the one task open to everyone.
const FUNDERS_ONLY: ImportAccess = { staff: false, stewardOf: [], orgs: [] };

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { headers: await authHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

/** The private files of each organisation the person belongs to. */
async function loadVault(access: ImportAccess): Promise<VaultFile[]> {
  return (await Promise.all(access.orgs.map(vaultFilesOf))).flat();
}

/** Staff get every panel; anyone else only what they researched, as the rest is the team's. */
async function loadPanels(): Promise<Panels> {
  // Research is open to everyone, so it need not wait for /api/me.
  const research = get<ResearchRecord[]>("/api/ingest/research?limit=25");
  research.catch(() => {}); // if /api/me fails first, this rejection is still awaited nowhere
  const access = accessOf(await get<Parameters<typeof accessOf>[0]>("/api/me"));
  const vault = loadVault(access).catch(() => []);
  if (!access.staff) {
    return { access, vaultFiles: await vault, sources: [], runs: [], queue: [], proposals: [], research: await research };
  }
  const [sources, runs, queue, proposals] = await Promise.all([
    get<ImportSource[]>("/api/ingest/sources"),
    get<ImportRun[]>("/api/ingest/runs?limit=8"),
    get<QueueItem[]>("/api/ingest/queue?limit=20"),
    get<SourceProposal[]>("/api/ingest/proposals?limit=20"),
  ]);
  return { access, vaultFiles: await vault, sources, runs, queue, proposals, research: await research };
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
