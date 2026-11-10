"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { MeOut } from "@/lib/api";
import { idParam, setUrlParams } from "@/lib/url";
import { useUrlThread } from "@/lib/useUrlThread";
import type { RegistryIndex } from "./lib/citations";
import { takePendingQuestion } from "./lib/pendingQuestion";
import { fetchThreads, loadThreads, type ThreadMeta } from "./lib/threads";
import type { Turn } from "./lib/useSangamChat";
import { ChatPane } from "./components/ChatPane";
import { EvidenceRail } from "./components/EvidenceRail";
import { Sidebar } from "./components/Sidebar";
import { isAskThreadId, viewFrom, viewParams } from "./lib/workspaceUrl";
import { VaultView } from "./views/VaultView";
import { MediaView } from "./views/media/MediaView";
import { RfpWatchView } from "./views/RfpWatchView";
import { ComingSoonView } from "./views/ComingSoonView";
import { COMING_SOON } from "./lib/comingSoon";
import { FunderMatchView } from "./views/FunderMatchView";
import { type ProposalTarget, ProposalsView } from "./views/ProposalsView";
import { useProposals } from "./views/proposals/api";
import { ChatsView } from "./views/ChatsView";

const newThreadId = () => crypto.randomUUID();

type Sourced = { sourceUrl: string | null; sourceName: string | null; fetchedAt: string | null };

export type IndexPayload = {
  orgs: ({ id: number; slug: string; name: string } & Sourced)[];
  funders: ({ id: number; slug: string; name: string } & Sourced)[];
  scores: { id: number; funderSlug: string; orgName: string; funderName: string; rubricVersion: string | null }[];
  activities: ({ id: number; href: string; title: string } & Sourced)[];
  stats: Record<string, number>;
  /** Staff or a steward: the sidebar offers Sangam Scout. */
  canScout: boolean;
  /** The page's /api/me, so a screen need not ask again; null when that call failed. */
  me: MeOut | null;
};

export function AskWorkspace({
  payload,
  initialQuestion = null,
}: {
  payload: IndexPayload;
  initialQuestion?: string | null;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const params = useSearchParams();
  const view = viewFrom(params.get("view"));
  const proposal = idParam(params.get("proposal"));
  const proposalFunder = idParam(params.get("funder"));
  const { threadId, resume, renew, markSent } = useUrlThread(newThreadId, { valid: isAskThreadId, active: view === "ask" });
  const [threads, setThreads] = useState<ThreadMeta[]>([]);
  // Both belong to one chat; Back to another must not show this one's evidence or prefill.
  const [latest, setLatest] = useState<{ thread: string; turn: Turn | null }>({ thread: "", turn: null });
  const [seed, setSeed] = useState<{ thread: string; text: string } | null>(null);
  const proposalCount = useProposals().length;

  useEffect(() => {
    setThreads(loadThreads());
    // Phones/small tablets: start with the workspace rail collapsed.
    if (window.matchMedia("(max-width: 768px)").matches) setCollapsed(true);
    // A question asked on the signed-out preview, or passed in ?q=: prefill it in a
    // fresh chat, unsent. The preview's question wins; it is the one the user typed.
    // ?q= is consumed here; dropping it means a reload does not prefill it again.
    const pending = takePendingQuestion() ?? initialQuestion;
    if (pending) setSeed({ thread: renew(), text: pending });
    setUrlParams({ q: null, ...(pending ? { thread: null } : {}) }, "replace");
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

  // The server's list once it answers; this browser's until then, or when it cannot.
  const refreshThreads = useCallback(() => {
    fetchThreads(threadId).then(setThreads, () => setThreads(loadThreads()));
  }, [threadId]);

  useEffect(() => {
    refreshThreads();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, on mount
  }, []);

  // Stable: ChatPane reports from an effect that lists it.
  const onLatestTurn = useCallback((turn: Turn | null) => setLatest({ thread: threadId, turn }), [threadId]);

  function openProposals(target: ProposalTarget) {
    setUrlParams({
      view: "proposals",
      proposal: target && "id" in target ? String(target.id) : null,
      funder: target && "funderId" in target ? String(target.funderId) : null,
    });
  }

  function pickThread(id: string) {
    setUrlParams({ ...viewParams("ask"), thread: id });
  }

  function newChat(seedText: string | null = null) {
    const id = renew();
    setSeed(seedText ? { thread: id, text: seedText } : null);
    setUrlParams({ ...viewParams("ask"), thread: null });
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
        // The screen you are on stays as it is; only Proposals, inside one proposal, goes back to the list.
        onView={(v) => (v !== view || proposal) && setUrlParams(viewParams(v))}
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
              seed={seed?.thread === threadId ? seed.text : null}
              onFirstSend={() => {
                if (!resume) markSent();
                refreshThreads();
              }}
              index={index}
              onLatestTurn={onLatestTurn}
            />
            <div className="evidence-rail-slot">
              <EvidenceRail latest={latest.thread === threadId ? latest.turn : null} stats={payload.stats} index={index} />
            </div>
          </>
        )}
        {view === "vault" && <VaultView orgs={payload.orgs} isStaff={payload.me?.is_staff ?? false} />}
        {view === "media" && <MediaView orgs={payload.orgs} me={payload.me} />}
        {view === "chats" && <ChatsView threads={threads} onPick={pickThread} />}
        {view === "funder-match" && (
          <FunderMatchView
            orgs={payload.orgs}
            me={payload.me}
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
            open={proposal}
            funder={proposalFunder}
            onOpen={(id) => setUrlParams({ proposal: id === null ? null : String(id) })}
            onFunderMatch={() => setUrlParams(viewParams("funder-match"))}
          />
        )}
        {view === "rfpwatch" &&
          (COMING_SOON.has("rfpwatch") ? (
            <ComingSoonView
              title="RFP Watch"
              body="Open calls and RFPs gathered every week, each shown with the organisations it plausibly fits."
            />
          ) : (
            <RfpWatchView orgs={payload.orgs} me={payload.me} onAsk={(q) => newChat(q)} onFunderMatch={() => setUrlParams(viewParams("funder-match"))} />
          ))}
      </div>
    </div>
  );
}
