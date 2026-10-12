import { apiGet } from "@/lib/api";
import { GraphWorkbench } from "./GraphWorkbench";
import type { GraphStatus } from "./graph-api";

export async function GraphPage() {
  const [me, status] = await Promise.all([
    apiGet<{ is_staff: boolean }>("/api/me").catch(() => null),
    apiGet<GraphStatus>("/api/graph/status").catch(() => null),
  ]);

  return (
    <div className="sangam-ui">
      <main className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-10">
        <div>
          <h1 className="text-2xl font-semibold">Knowledge graph</h1>
          <p className="text-sm text-neutral-600">
            Add text or Storage documents to Graphiti, see the entities and facts each chunk produced, and search
            what is there.
          </p>
        </div>
        {!me ? (
          <p className="text-sm text-neutral-700">Sign in to use the knowledge graph.</p>
        ) : !me.is_staff ? (
          <p className="text-sm text-neutral-700">Adding to the knowledge graph is for Sangam staff.</p>
        ) : (
          <GraphWorkbench status={status} />
        )}
      </main>
    </div>
  );
}
