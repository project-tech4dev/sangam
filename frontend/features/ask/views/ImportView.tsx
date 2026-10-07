"use client";

import { useEffect, useState } from "react";
import { ImportWorkspace } from "@/features/ingest/ImportWorkspace";
import { ProposalList } from "@/features/ingest/components/ProposalList";
import { ResearchShelf } from "@/features/ingest/components/ResearchShelf";
import { ReviewQueue } from "@/features/ingest/components/ReviewQueue";
import { RunHistory } from "@/features/ingest/components/RunHistory";
import { SourcePanel } from "@/features/ingest/components/SourcePanel";
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
 * Sangam Import, inside the Ask workspace: the import agent's chat with the run, research,
 * review and source panels beside it. The panels load when the view opens rather than with
 * every /ask page, since most visits never open Tools.
 */
export function ImportView() {
  const [panels, setPanels] = useState<Panels | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [staffOnly, setStaffOnly] = useState(false);

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
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="eyebrow">Tools · Import</div>
        <h2 style={{ fontSize: "var(--fs-lg)" }}>Staff only</h2>
        <p className="muted measure" style={{ margin: "6px 0 0" }}>
          Sangam Import changes the catalog, so it is open to the Sangam team only. Ask Sangam is
          open to you.
        </p>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <div className="eyebrow">Tools · Import</div>
        <h2 style={{ fontSize: "var(--fs-lg)" }}>Bring funder data in, and see what could not come in</h2>
        <p className="muted measure" style={{ margin: "6px 0 0" }}>
          Sangam Import reads the sources whose terms allow it, matches what it finds against the
          catalog, and writes what is safe to write. It is not Ask Sangam — it changes the data.
        </p>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 28, alignItems: "flex-start" }}>
        <div style={{ flex: "1 1 480px", minWidth: 0 }}>
          <ImportWorkspace />
        </div>
        <aside style={{ flex: "1 1 300px", maxWidth: 400, display: "grid", gap: 24 }}>
          {error && <div className="card-body" style={{ color: "var(--color-bad)" }}>Could not load the import panels: {error}</div>}
          {!panels && !error && <div className="muted">Loading runs and research…</div>}
          {panels && (
            <>
              <ResearchShelf items={panels.research} />
              <RunHistory runs={panels.runs} />
              <ReviewQueue items={panels.queue} />
              <ProposalList items={panels.proposals} />
            </>
          )}
        </aside>
      </div>
      {panels && <SourcePanel sources={panels.sources} />}
    </div>
  );
}
