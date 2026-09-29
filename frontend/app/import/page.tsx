import { apiGet } from "@/lib/api";
import { Nav } from "@/components/layout/Nav";
import { ImportWorkspace } from "@/features/ingest/ImportWorkspace";
import { RunHistory } from "@/features/ingest/components/RunHistory";
import { ReviewQueue } from "@/features/ingest/components/ReviewQueue";
import { SourcePanel } from "@/features/ingest/components/SourcePanel";
import type { ImportRun, ImportSource, QueueItem } from "@/features/ingest/lib/types";

export const metadata = { title: "Sangam Import" };
export const dynamic = "force-dynamic";

export default async function ImportPage() {
  const [sources, runs, queue] = await Promise.all([
    apiGet<ImportSource[]>("/api/ingest/sources"),
    apiGet<ImportRun[]>("/api/ingest/runs?limit=8"),
    apiGet<QueueItem[]>("/api/ingest/queue?limit=20"),
  ]);

  return (
    <>
      <Nav current="import" />
      <main
        style={{
          maxWidth: "var(--page-max)",
          margin: "0 auto",
          padding: "28px var(--page-pad) 64px",
          display: "grid",
          gap: 28,
          gridTemplateColumns: "minmax(0, 1fr) minmax(320px, 420px)",
          alignItems: "start",
        }}
      >
        <div style={{ display: "grid", gap: 24 }}>
          <header>
            <h1 style={{ fontSize: 40, margin: "0 0 6px" }}>Sangam Import</h1>
            <p style={{ color: "var(--color-muted)", margin: 0, maxWidth: "60ch" }}>
              Bring funder data in from outside sources, match it against the catalog, and see what
              could not be brought in. This is not Ask Sangam — it changes the data.
            </p>
          </header>
          <ImportWorkspace />
        </div>
        <aside style={{ display: "grid", gap: 24 }}>
          <RunHistory runs={runs} />
          <ReviewQueue items={queue} />
          <SourcePanel sources={sources} />
        </aside>
      </main>
    </>
  );
}
