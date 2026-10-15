"use client";

import { useSyncExternalStore } from "react";
import type { Message } from "@ag-ui/client";
import { ApiError, call } from "../../lib/rest";

export type Answer = "yes" | "will_have" | "no";

export type Requirement = { key: string; label: string; rule: string; on_record: string; hard: boolean };

export type Summary = {
  stage: number;
  gates_answered: number;
  gates_total: number;
  done: number;
  total: number;
  fix_first: string[];
  worth_checking: string[];
  ready: boolean;
  /** What stops the open step being left, in words; empty when Next is allowed. */
  to_continue?: string[];
};

export type Work = {
  stage: number;
  requirements: Requirement[];
  gates: Record<string, Answer | null>;
  earlier_phase: boolean;
  template: { document_id: number; url: string | null; from: "sangam" | "upload"; read_at: string | null } | null;
  skipped_template: boolean;
  sources: number[];
  style: string;
  sections: Record<string, { text?: string; done?: boolean; rev?: number; score?: number; needs_rewrite?: boolean }>;
  facts?: Record<string, Fact>;
  questions?: Record<string, { section: string; subject: string; status: "open" | "parked" | "answered" | "closed"; asked_of: { id: string; name: string } | null }>;
  /** Keyed by document id, plus "funder" for what the funder looks for. */
  readers?: Record<string, Reader>;
};

export type Reader = { status: "running" | "done" | "failed"; at: string; by?: { id: string; name: string }; title: string; error?: string };

/** One fact in the proposal's list; the screen shows its standing and source in words, never its id or marker. */
export type Fact = {
  subject: string;
  value: string;
  origin: "registry" | "vault" | "web" | "you_said" | "derived";
  tier: "green" | "amber" | "said";
  status: "proposed" | "confirmed" | "corrected" | "rejected";
  section?: string;
  as_of?: string;
  marker?: string;
  source_name?: string;
  page?: number;
  said_by?: { id: string; name: string };
  document_id?: number;
  /** The parts whose text cites it. */
  used_in?: string[];
};

export type ProposalItem = {
  id: number;
  title: string;
  org: { id: number; slug: string; name: string };
  funder: { id: number; slug: string; name: string };
  fit_score: number | null;
  created_at: string;
  updated_at: string;
  summary: Summary;
  can_edit: boolean;
};

export type Section = { code: string; label: string; question: string; tab: string; strong: string[]; weak: string };
export type Tab = { key: string; label: string; question: string };
export type Proposal = ProposalItem & { /** The caller's own chat; teammates each have theirs. */ thread_id: string; work: Work; sections: Section[]; tabs: Tab[] };
export type Saved = { summary: Summary; work: Work };
export type ChangedBy = { by: { id: string; name: string }; at: string } | null;

// Every proposal the caller may read, shared by the workspace count, Funder Match and the list.
let rows: ProposalItem[] | null = null;
let loading = false;
const EMPTY: ProposalItem[] = [];
const listeners = new Set<() => void>();

export async function reloadProposals() {
  loading = true;
  try {
    rows = await call<ProposalItem[]>("/api/proposals");
  } catch {
    rows = rows ?? [];
  } finally {
    loading = false;
  }
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (rows === null && !loading) void reloadProposals();
  return () => listeners.delete(listener);
}

export const useProposals = () => useSyncExternalStore(subscribe, () => rows ?? EMPTY, () => EMPTY);

export async function startProposal(org: string, funderId: number, title: string): Promise<number> {
  const { id } = await call<{ id: number }>("/api/proposals", "POST", { org, funder_id: funderId, title });
  void reloadProposals();
  return id;
}

export const getProposal = (id: number) => call<Proposal>(`/api/proposals/${id}`);

/** The proposal's shared chat, as the backend rebuilt it; empty before anyone has asked. */
export async function fetchProposalMessages(id: number): Promise<Message[]> {
  try {
    return (await call<{ messages: Message[] }>(`/api/proposals/${id}/messages`)).messages;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return [];
    throw error;
  }
}

export async function saveWork(id: number, set: Record<string, unknown>, rev: Record<string, number> = {}) {
  const saved = await call<Saved>(`/api/proposals/${id}/work`, "PATCH", { set, rev });
  void reloadProposals();
  return saved;
}

export async function rename(id: number, title: string) {
  const saved = await call<Saved>(`/api/proposals/${id}`, "PATCH", { title });
  void reloadProposals();
  return saved;
}

export async function advance(id: number) {
  const saved = await call<Saved>(`/api/proposals/${id}/advance`, "POST");
  void reloadProposals();
  return saved;
}

/** "Ravi changed this a minute ago. Showing his version." from a 409, or null for any other failure. */
export function changedByLine(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const detail = (error.body as { detail?: { changed_by?: ChangedBy } } | null)?.detail;
  const who = detail?.changed_by;
  if (!who) return "Someone changed this since you opened it. Showing the latest version.";
  const minutes = Math.max(0, Math.round((Date.now() - Date.parse(who.at)) / 60_000));
  const ago = minutes < 1 ? "just now" : minutes === 1 ? "a minute ago" : minutes < 60 ? `${minutes} minutes ago` : "earlier";
  return `${who.by.name} changed this ${ago}. Showing their version.`;
}

/** What step 1 or 2 still needs, from a refused advance. */
export function missingFrom(error: unknown): string[] | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const detail = (error.body as { detail?: { missing?: string[] } } | null)?.detail;
  return detail?.missing ?? null;
}

// Proposals made before they lived on the server were kept in one browser only.
export function hadBrowserProposals(): boolean {
  try {
    const kept = JSON.parse(window.localStorage.getItem("sangam.proposals.v1") ?? "[]");
    return Array.isArray(kept) && kept.length > 0;
  } catch {
    return false;
  }
}
