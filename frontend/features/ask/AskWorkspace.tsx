"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { RegistryIndex } from "./lib/citations";
import { takePendingQuestion } from "./lib/pendingQuestion";
import { loadThreads, type ThreadMeta } from "./lib/threads";
import type { Turn } from "./lib/useSangamChat";
import { ChatPane } from "./components/ChatPane";
import { EvidenceRail } from "./components/EvidenceRail";
import { Sidebar, type WorkspaceView } from "./components/Sidebar";
import { VaultView } from "./views/VaultView";
import { MediaView } from "./views/MediaView";
import { RfpWatchView } from "./views/RfpWatchView";
import dynamic from "next/dynamic";

// Most visits never open Tools, so the ingest UI downloads only when Import is first opened.
const ImportView = dynamic(() => import("./views/ImportView").then((m) => m.ImportView));

export type IndexPayload = {
  orgs: { id: number; slug: string; name: string }[];
  funders: { id: number; slug: string; name: string }[];
  scores: { id: number; funderSlug: string; orgName: string; funderName: string }[];
  grants: { id: number; orgSlug: string; title: string }[];
  stats: Record<string, number>;
};

export function AskWorkspace({
  payload,
  initialQuestion = null,
  initialView = "ask",
}: {
  payload: IndexPayload;
  initialQuestion?: string | null;
  initialView?: WorkspaceView;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [view, setView] = useState<WorkspaceView>(initialView);
  // Once opened, Import stays mounted (hidden when another view shows): its chat holds the
  // run's thread, and unmounting it would drop a run the agent is still working on.
  const [importOpened, setImportOpened] = useState(initialView === "import");
  if (view === "import" && !importOpened) setImportOpened(true);
  const [threadId, setThreadId] = useState(() => crypto.randomUUID());
  const [threads, setThreads] = useState<ThreadMeta[]>([]);
  const [latestTurn, setLatestTurn] = useState<Turn | null>(null);
  const [seed, setSeed] = useState<string | null>(null);

  useEffect(() => {
    setThreads(loadThreads());
    // Phones/small tablets: start with the workspace rail collapsed.
    if (window.matchMedia("(max-width: 768px)").matches) setCollapsed(true);
    // A question asked on the signed-out preview, or passed in ?q=: prefill it in a
    // fresh chat, unsent. The preview's question wins; it is the one the user typed.
    const pending = takePendingQuestion() ?? initialQuestion;
    if (pending) {
      setThreadId(crypto.randomUUID());
      setSeed(pending);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, on mount
  }, []);

  const index: RegistryIndex = useMemo(
    () => ({
      orgs: new Map(payload.orgs.map((o) => [o.id, o])),
      funders: new Map(payload.funders.map((f) => [f.id, f])),
      scores: new Map(payload.scores.map((s) => [s.id, s])),
      grants: new Map(payload.grants.map((g) => [g.id, g])),
    }),
    [payload],
  );

  // Tools live in the URL (?view=import) so they can be linked to and survive a reload.
  // ?q= is consumed once on mount; drop it so a reload does not prefill it again.
  useEffect(() => {
    const url = new URL(window.location.href);
    if (view === "import") url.searchParams.set("view", view);
    else url.searchParams.delete("view");
    url.searchParams.delete("q");
    window.history.replaceState(null, "", url);
  }, [view]);

  const refreshThreads = useCallback(() => setThreads(loadThreads()), []);

  function newChat(seedText: string | null = null) {
    setThreadId(crypto.randomUUID());
    setSeed(seedText);
    setLatestTurn(null);
    setView("ask");
  }

  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        display: "flex",
        background: "var(--color-surface)",
        overflow: "hidden",
        position: "relative",
      }}
    >
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed(!collapsed)}
        view={view}
        onView={setView}
        threads={threads}
        activeThread={threadId}
        onPickThread={(id) => {
          setThreadId(id);
          setSeed(null);
          setLatestTurn(null);
          setView("ask");
        }}
        onNewChat={() => newChat()}
      />

      <div className="ask-main" style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", gap: 24 }}>
        {view === "ask" && (
          <>
            <ChatPane
              key={threadId}
              threadId={threadId}
              seed={seed}
              onFirstSend={refreshThreads}
              index={index}
              onLatestTurn={setLatestTurn}
            />
            <div className="evidence-rail-slot">
              <EvidenceRail latest={latestTurn} stats={payload.stats} index={index} />
            </div>
          </>
        )}
        {view === "vault" && <VaultView orgs={payload.orgs} />}
        {view === "media" && <MediaView onDiscuss={(text) => newChat(text)} />}
        {view === "rfpwatch" && <RfpWatchView />}
        {importOpened && (
          <div style={{ display: view === "import" ? "flex" : "none", flex: 1, minWidth: 0, minHeight: 0 }}>
            <ImportView />
          </div>
        )}
      </div>
    </div>
  );
}
