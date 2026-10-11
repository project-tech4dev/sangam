"use client";

import type { Message } from "@ag-ui/client";
import { titleFrom, type ThreadMeta } from "@/features/ask/lib/threads";
import { authHeaders } from "@/lib/api/auth-headers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

export const newImportId = () => `import-${crypto.randomUUID()}`;

type ThreadRow = { thread_id: string; title: string | null; created_at: string };

/** The signed-in staff member's Import threads, newest first. */
export async function fetchImportThreads(): Promise<ThreadMeta[]> {
  const res = await fetch(`${API}/api/ingest/threads`, { headers: await authHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error(`Could not load past imports (${res.status}).`);
  const rows: ThreadRow[] = await res.json();
  return rows.map((r) => ({
    id: r.thread_id,
    title: r.title ? titleFrom(r.title) : "Untitled chat",
    createdAt: Date.parse(r.created_at),
  }));
}

/** A past import's saved messages; none when it never reached the server. */
export async function fetchImportMessages(threadId: string): Promise<Message[]> {
  const res = await fetch(`${API}/api/ingest/threads/${encodeURIComponent(threadId)}/messages`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  if (res.status === 404) return [];
  if (!res.ok) throw new Error(`Could not load this chat (${res.status}).`);
  return (await res.json()).messages;
}

export type LiveStep = { owner: string | null; tool: string; running: boolean };
export type LiveAnswer = { answer: string; kind: "status" | "instruction" };

/** Asks about a run while it is still researching; answered from its state, the run itself untouched. */
export async function askLive(threadId: string, question: string, since: number | null, steps: LiveStep[]): Promise<LiveAnswer> {
  const res = await fetch(`${API}/api/ingest/threads/${encodeURIComponent(threadId)}/ask-live`, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify({ question, since: since ? new Date(since).toISOString() : null, steps }),
  });
  if (!res.ok) throw new Error(`Scout could not answer right now (${res.status}).`);
  return res.json();
}
