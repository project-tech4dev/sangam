"use client";

import type { Message } from "@ag-ui/client";
import { authHeaders } from "@/lib/api/auth-headers";

export type ThreadMeta = { id: string; title: string; createdAt: number };

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";
const KEY = "sangam_threads_v1";

// localStorage is now only a fallback: the title of a chat saved before the server kept titles,
// and the chat just started, until its first turn reaches the server.
export function loadThreads(): ThreadMeta[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function saveThread(thread: ThreadMeta): void {
  const threads = loadThreads().filter((t) => t.id !== thread.id);
  threads.unshift(thread);
  localStorage.setItem(KEY, JSON.stringify(threads.slice(0, 50)));
}

export function titleFrom(question: string): string {
  const trimmed = question.trim().replace(/\s+/g, " ");
  return trimmed.length > 56 ? `${trimmed.slice(0, 56)}…` : trimmed;
}

type ThreadRow = { thread_id: string; title: string | null; created_at: string; updated_at: string };

/** The signed-in user's chats from the server, newest first; the active chat stays listed while it is new. */
export async function fetchThreads(activeId: string): Promise<ThreadMeta[]> {
  const res = await fetch(`${API}/api/threads`, { headers: await authHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error(`Could not load chats (${res.status}).`);
  const rows: ThreadRow[] = await res.json();
  const local = new Map(loadThreads().map((t) => [t.id, t]));
  const threads = rows.map((r) => ({
    id: r.thread_id,
    title: r.title ? titleFrom(r.title) : (local.get(r.thread_id)?.title ?? "Untitled chat"),
    createdAt: Date.parse(r.created_at),
  }));
  const active = local.get(activeId);
  if (active && !threads.some((t) => t.id === activeId)) threads.unshift(active);
  return threads;
}

/** A past chat's saved messages; none when the chat is not on the server yet. */
export async function fetchThreadMessages(threadId: string): Promise<Message[]> {
  const res = await fetch(`${API}/api/threads/${encodeURIComponent(threadId)}/messages`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  if (res.status === 404) return [];
  if (!res.ok) throw new Error(`Could not load this chat (${res.status}).`);
  return (await res.json()).messages;
}
