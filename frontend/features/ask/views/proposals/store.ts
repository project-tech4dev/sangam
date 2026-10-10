"use client";

import { useSyncExternalStore } from "react";
import { type GateKey, GATES, sectionsFor } from "./rubric";

export type Gate = { rule: string; bars: string[]; on_record: string };

export type Work = {
  rubric_version: string;
  step: number;
  gates: Partial<Record<GateKey, boolean>>;
  funder_gates: Record<GateKey, Gate>;
  earlier_phase: boolean;
  template: { document_id: number; url: string | null; from: "sangam" | "upload"; read_at: string | null } | null;
  skipped_template: boolean;
  docs: number[];
  style: string;
  sections: Record<string, { text?: string; done?: boolean }>;
};

export type Proposal = {
  id: string;
  title: string;
  org: { slug: string; name: string };
  funder: { id: number; slug: string; name: string };
  fit_score: number | null;
  created_at: string;
  updated_at: string;
  work: Work;
};

// Proposals live in this browser for now: no table yet, so another person or device does not see them.
const KEY = "sangam.proposals.v1";
const EMPTY: Proposal[] = [];
const listeners = new Set<() => void>();
let cache: Proposal[] | null = null;

function read(): Proposal[] {
  if (cache) return cache;
  try {
    const parsed = JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
    cache = Array.isArray(parsed) ? parsed : [];
  } catch {
    cache = [];
  }
  return cache!;
}

function write(next: Proposal[]) {
  cache = next;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Private windows and full storage: the change lasts until the page reloads.
  }
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key !== KEY) return;
    cache = null;
    listener();
  };
  listeners.add(listener);
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** Every proposal in this browser, newest first. */
export const useProposals = () => useSyncExternalStore(subscribe, read, () => EMPTY);

export function addProposal(p: Proposal) {
  write([p, ...read()]);
}

/** Merges a change into one proposal's work, or renames it. */
export function updateProposal(id: string, change: { title?: string; work?: Partial<Work> }) {
  const now = new Date().toISOString();
  write(
    read().map((p) =>
      p.id === id ? { ...p, ...(change.title ? { title: change.title } : {}), work: { ...p.work, ...change.work }, updated_at: now } : p,
    ),
  );
}

export function summary(work: Work) {
  const codes = sectionsFor(work.earlier_phase).map((s) => s.code);
  const done = codes.filter((c) => work.sections[c]?.done).length;
  const gatesMet = (Object.keys(GATES) as GateKey[]).filter((g) => work.gates[g]).length;
  const gates = Object.keys(GATES).length;
  return { step: work.step, done, total: codes.length, gatesMet, gates, ready: gatesMet === gates && done === codes.length };
}
