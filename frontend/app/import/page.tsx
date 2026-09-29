import { apiGet } from "@/lib/api";
import { Breadcrumbs } from "@/components/ui";
import { ImportWorkspace } from "@/features/ingest/ImportWorkspace";
import { RunHistory } from "@/features/ingest/components/RunHistory";
import { ReviewQueue } from "@/features/ingest/components/ReviewQueue";
import { SourcePanel } from "@/features/ingest/components/SourcePanel";
import { ProposalList } from "@/features/ingest/components/ProposalList";
import { ResearchShelf } from "@/features/ingest/components/ResearchShelf";
import type {
  ImportRun,
  ImportSource,
  QueueItem,
  ResearchRecord,
  SourceProposal,
} from "@/features/ingest/lib/types";

export const metadata = { title: "Import — Sangam" };
export const dynamic = "force-dynamic";

// The nav comes from the root layout; this page renders only its own content.
export default async function ImportPage() {
  const [sources, runs, queue, proposals, research] = await Promise.all([
    apiGet<ImportSource[]>("/api/ingest/sources"),
    apiGet<ImportRun[]>("/api/ingest/runs?limit=8"),
    apiGet<QueueItem[]>("/api/ingest/queue?limit=20"),
    apiGet<SourceProposal[]>("/api/ingest/proposals?limit=20"),
    apiGet<ResearchRecord[]>("/api/ingest/research?limit=25"),
  ]);

  return (
    <div className="page" style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <Breadcrumbs items={[{ label: "Sangam", href: "/registry" }, { label: "Import" }]} />
      <div>
        <div className="eyebrow">Import</div>
        <h1 style={{ fontSize: 28 }}>Bring funder data in, and see what could not come in</h1>
        <p style={{ color: "var(--color-muted)", margin: "6px 0 0", maxWidth: "62ch" }}>
          Sangam Import reads the sources whose terms allow it, matches what it finds against the
          catalog, and writes what is safe to write. It is not Ask Sangam — it changes the data.
        </p>
      </div>
      <div
        style={{
          display: "grid",
          gap: 28,
          gridTemplateColumns: "minmax(0, 1fr) minmax(300px, 400px)",
          alignItems: "start",
        }}
      >
        <ImportWorkspace />
        <aside style={{ display: "grid", gap: 24 }}>
          <ResearchShelf items={research} />
          <RunHistory runs={runs} />
          <ReviewQueue items={queue} />
          <ProposalList items={proposals} />
        </aside>
      </div>
      <SourcePanel sources={sources} />
    </div>
  );
}
