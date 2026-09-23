"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { RegistryIndex } from "./lib/citations";
import { loadThreads, type ThreadMeta } from "./lib/threads";
import type { Turn } from "./lib/useSangamChat";
import { ChatPane } from "./components/ChatPane";
import { EvidenceRail } from "./components/EvidenceRail";
import { Sidebar, type WorkspaceView } from "./components/Sidebar";
import { VaultView } from "./views/VaultView";
import { MediaView } from "./views/MediaView";
import { RfpWatchView } from "./views/RfpWatchView";

export type IndexPayload = {
  orgs: { id: number; slug: string; name: string }[];
  funders: { id: number; slug: string; name: string }[];
  scores: { id: number; funderSlug: string; orgName: string; funderName: string }[];
  grants: { id: number; orgSlug: string; title: string }[];
  stats: Record<string, number>;
};

export function AskWorkspace({ payload }: { payload: IndexPayload }) {
  const [collapsed, setCollapsed] = useState(false);
  const [view, setView] = useState<WorkspaceView>("ask");
  const [threadId, setThreadId] = useState(() => crypto.randomUUID());
  const [threads, setThreads] = useState<ThreadMeta[]>([]);
  const [latestTurn, setLatestTurn] = useState<Turn | null>(null);
  const [seed, setSeed] = useState<string | null>(null);

  useEffect(() => {
    setThreads(loadThreads());
    // Phones/small tablets: start with the workspace rail collapsed.
    if (window.matchMedia("(max-width: 768px)").matches) setCollapsed(true);
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
      </div>
    </div>
  );
}
