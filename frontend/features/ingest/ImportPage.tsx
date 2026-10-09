"use client";

import { useCallback, useEffect, useState } from "react";
import { titleFrom, type ThreadMeta } from "@/features/ask/lib/threads";
import { AgentProviders } from "@/lib/AgentProviders";
import { ImportThreads } from "./components/ImportThreads";
import { ImportView } from "./ImportView";
import { fetchImportThreads, newImportId } from "./lib/threads";

/** Puts the open thread in the address, so a reload or a shared link reopens it. */
function showInUrl(threadId: string | null) {
  const url = new URL(window.location.href);
  if (threadId) url.searchParams.set("thread", threadId);
  else url.searchParams.delete("thread");
  window.history.replaceState(null, "", url);
}

function ImportShell({ initialThread }: { initialThread: string | null }) {
  const [threadId, setThreadId] = useState(() => initialThread ?? newImportId());
  // A thread from the address or the list loads its saved messages; a new one has none.
  const [resume, setResume] = useState(Boolean(initialThread));
  const [threads, setThreads] = useState<ThreadMeta[] | null>(null);
  const [error, setError] = useState(false);
  // Phones start with the list closed; it opens over the page. Safe here: this renders only in the browser.
  const [collapsed, setCollapsed] = useState(() => window.matchMedia("(max-width: 768px)").matches);

  const refresh = useCallback(() => {
    fetchImportThreads().then(
      (rows) => {
        setError(false);
        // A run that just started may not be listed yet; keep the one already shown.
        setThreads((prev) => {
          const pending = prev?.find((t) => t.id === threadId && !rows.some((r) => r.id === t.id));
          return pending ? [pending, ...rows] : rows;
        });
      },
      () => setError(true),
    );
  }, [threadId]);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, on mount
  }, []);

  function open(id: string | null) {
    setThreadId(id ?? newImportId());
    setResume(id !== null);
    showInUrl(id);
    if (window.matchMedia("(max-width: 768px)").matches) setCollapsed(true);
  }

  function firstSend(text: string) {
    showInUrl(threadId);
    setThreads((prev) => [{ id: threadId, title: titleFrom(text), createdAt: Date.now() }, ...(prev ?? [])]);
  }

  return (
    <div className="import-layout">
      <ImportThreads
        threads={threads}
        active={threadId}
        error={error}
        collapsed={collapsed}
        onToggle={() => setCollapsed(!collapsed)}
        onPick={open}
        onNew={() => open(null)}
      />
      <div className="ask-main import-layout-main">
        <ImportView
          threadId={threadId}
          resume={resume}
          onStartOver={() => open(null)}
          onFirstSend={(text) => {
            firstSend(text);
            // The server titles the thread when its run starts.
            setTimeout(refresh, 3000);
          }}
        />
      </div>
    </div>
  );
}

export function ImportPage({ initialThread }: { initialThread: string | null }) {
  return (
    <AgentProviders>
      <ImportShell initialThread={initialThread} />
    </AgentProviders>
  );
}
