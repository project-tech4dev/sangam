"use client";

export type ThreadMeta = { id: string; title: string; createdAt: number };

const KEY = "sangam_threads_v1";

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
