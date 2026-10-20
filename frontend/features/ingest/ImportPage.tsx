"use client";

import { useCallback, useEffect, useState } from "react";
import { titleFrom, type ThreadMeta } from "@/features/ask/lib/threads";
import { AgentProviders } from "@/lib/AgentProviders";
import { setUrlParams } from "@/lib/url";
import { useUrlThread } from "@/lib/useUrlThread";
import { ImportThreads } from "./components/ImportThreads";
import { ImportView } from "./ImportView";
import { fetchImportThreads, isImportId, newImportId } from "./lib/threads";

function ImportShell() {
  const { threadId, resume, renew, markSent } = useUrlThread(newImportId, { valid: isImportId });
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

  // Each pick is a Back step; a new import is the bare /import.
  function open(id: string | null) {
    if (id === null) renew();
    setUrlParams({ thread: id });
    if (window.matchMedia("(max-width: 768px)").matches) setCollapsed(true);
  }

  function firstSend(text: string) {
    if (!resume) markSent();
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

export function ImportPage() {
  return (
    <AgentProviders>
      <ImportShell />
    </AgentProviders>
  );
}
