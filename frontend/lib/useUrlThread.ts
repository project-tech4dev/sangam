"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { setUrlParams } from "./url";

/**
 * The open chat is `?thread=`; with none it is an unsent draft. A draft enters the address on its first
 * send, and once left it is a saved chat like any other, so Back to it loads its messages.
 */
export function useUrlThread(newId: () => string, { valid = () => true, active = true }: {
  valid?: (id: string) => boolean;
  active?: boolean;
} = {}) {
  const raw = useSearchParams().get("thread");
  const param = raw && valid(raw) ? raw : null;
  const [draft, setDraft] = useState(newId);
  const sent = useRef<string | null>(null);

  useEffect(() => {
    if (sent.current === draft && (!active || param !== draft)) {
      sent.current = null;
      setDraft(newId());
    }
  }, [active, param, draft, newId]);

  const threadId = param ?? draft;
  return {
    threadId,
    resume: threadId !== draft,
    /** A fresh draft; the caller clears `thread` from the address in the same write as its other params. */
    renew() {
      const id = newId();
      setDraft(id);
      return id;
    },
    /** The draft's first send: name it in the address without adding a Back step. */
    markSent() {
      sent.current = draft;
      setUrlParams({ thread: draft }, "replace");
    },
  };
}
