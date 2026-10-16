"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { RegistryIndex } from "./lib/citations";
import { takePendingQuestion } from "./lib/pendingQuestion";
import { fetchThreads, loadThreads, type ThreadMeta } from "./lib/threads";
import type { Turn } from "./lib/useSangamChat";
import { ChatPane } from "./components/ChatPane";
import { EvidenceRail } from "./components/EvidenceRail";
import { Sidebar, type WorkspaceView } from "./components/Sidebar";
import { VaultView } from "./views/VaultView";
import { MediaView } from "./views/media/MediaView";
import { RfpWatchView } from "./views/RfpWatchView";
import { ComingSoonView } from "./views/ComingSoonView";
import { COMING_SOON } from "./lib/comingSoon";
import { FunderMatchView } from "./views/FunderMatchView";
import { type ProposalTarget, ProposalsView } from "./views/ProposalsView";
import { useProposals } from "./views/proposals/api";
import { ChatsView } from "./views/ChatsView";

type Sourced = { sourceUrl: string | null; sourceName: string | null; fetchedAt: string | null };

export type IndexPayload = {
  orgs: ({ id: number; slug: string; name: string } & Sourced)[];
  funders: ({ id: number; slug: string; name: string } & Sourced)[];
  scores: { id: number; funderSlug: string; orgName: string; funderName: string; rubricVersion: string | null }[];
  activities: ({ id: number; href: string; title: string } & Sourced)[];
  stats: Record<string, number>;
  /** Staff or a steward: the sidebar offers Sangam Scout. */
  canScout: boolean;
};

export function AskWorkspace({
  payload,
  initialQuestion = null,
}: {
  payload: IndexPayload;
  initialQuestion?: string | null;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [view, setView] = useState<WorkspaceView>("ask");
  const [threadId, setThreadId] = useState(() => crypto.randomUUID());
  // A chat picked from the list loads its saved messages; a new one has none.
  const [resume, setResume] = useState(false);
  const [threads, setThreads] = useState<ThreadMeta[]>([]);
  const [latestTurn, setLatestTurn] = useState<Turn | null>(null);
  const [seed, setSeed] = useState<string | null>(null);
  const [proposalTarget, setProposalTarget] = useState<{ key: number; target: ProposalTarget }>({ key: 0, target: null });
  const proposalCount = useProposals().length;

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
      activities: new Map(payload.activities.map((a) => [a.id, a])),
    }),
    [payload],
  );

  // ?q= is consumed once on mount; drop it so a reload does not prefill it again.
  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.delete("q");
    window.history.replaceState(null, "", url);
  }, []);

  // The server's list once it answers; this browser's until then, or when it cannot.
  const refreshThreads = useCallback(() => {
    fetchThreads(threadId).then(setThreads, () => setThreads(loadThreads()));
  }, [threadId]);

  useEffect(() => {
    refreshThreads();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, on mount
  }, []);

  // A new key remounts Proposals on that proposal or that funder's list.
  function openProposals(target: ProposalTarget) {
    setProposalTarget((t) => ({ key: t.key + 1, target }));
    setView("proposals");
  }

  function pickThread(id: string) {
    setThreadId(id);
    setResume(true);
    setSeed(null);
    setLatestTurn(null);
    setView("ask");
  }

  function newChat(seedText: string | null = null) {
    setThreadId(crypto.randomUUID());
    setResume(false);
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
        onView={(v) => (v === "proposals" ? openProposals(null) : setView(v))}
        threads={threads}
        activeThread={threadId}
        onPickThread={pickThread}
        onNewChat={() => newChat()}
        counts={{ proposals: proposalCount }}
        canScout={payload.canScout}
      />

      <div className="ask-main" style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", gap: 24 }}>
        {view === "ask" && (
          <>
            <ChatPane
              key={threadId}
              threadId={threadId}
              resume={resume}
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
        {view === "media" && <MediaView orgs={payload.orgs} />}
        {view === "chats" && <ChatsView threads={threads} onPick={pickThread} />}
        {view === "funder-match" && (
          <FunderMatchView
            orgs={payload.orgs}
            nav={{ open: (id) => openProposals({ id }), list: (funderId) => openProposals({ funderId }) }}
          />
        )}
        {view === "proposals" && COMING_SOON.has("proposals") && (
          <ComingSoonView
            title="Proposals"
            body="Draft a proposal to a matched funder, checked section by section against what the funder asks for and grounded in your own documents."
          />
        )}
        {view === "proposals" && !COMING_SOON.has("proposals") && (
          <ProposalsView
            key={proposalTarget.key}
            target={proposalTarget.target}
            onFunderMatch={() => setView("funder-match")}
          />
        )}
        {view === "rfpwatch" &&
          (COMING_SOON.has("rfpwatch") ? (
            <ComingSoonView
              title="RFP Watch"
              body="Open calls and RFPs gathered every week, each shown with the organisations it plausibly fits."
            />
          ) : (
            <RfpWatchView orgs={payload.orgs} onAsk={(q) => newChat(q)} onFunderMatch={() => setView("funder-match")} />
          ))}
      </div>
    </div>
  );
}
