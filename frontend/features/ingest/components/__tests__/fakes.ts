import { vi } from "vitest";
import type { ImportSource, QueueItem, ResearchCoverage, ResearchReview } from "../../lib/types";

const STATUS = Symbol("status");
type Shaped = { [STATUS]: number; body: unknown };
/** A reply with a non-200 status. */
export const status = (code: number, body: unknown = null): Shaped => ({ [STATUS]: code, body });

type Reply = unknown;

/** A fetch stub that answers by the first matching path fragment; unmatched paths are a 404. */
export function stubFetch(routes: Record<string, Reply | (() => Reply)>) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    void init;
    const hit = Object.keys(routes).find((k) => String(url).includes(k));
    const raw = hit === undefined ? status(404) : routes[hit];
    const reply = typeof raw === "function" ? (raw as () => Reply)() : raw;
    if (reply instanceof Error) throw reply;
    const shaped = reply !== null && typeof reply === "object" && STATUS in (reply as object);
    const code = shaped ? (reply as Shaped)[STATUS] : 200;
    const body = shaped ? (reply as Shaped).body : reply;
    return { ok: code < 400, status: code, json: async () => body } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export const source = (over: Partial<ImportSource> = {}): ImportSource => ({
  key: "csr",
  name: "CSR Portal",
  host: "csr.gov.in",
  access_rule: "open_api",
  basis: "Government open data",
  categories: ["funder"],
  yields: ["grants"],
  dispatchable: true,
  has_adapter: true,
  robots_checked_at: null,
  ...over,
});

export const queueItem = (over: Partial<QueueItem> = {}): QueueItem => ({
  id: 1,
  raw_name: "Tata Trust",
  entity_kind: "funder",
  source: "csr",
  candidates: [{ id: 9, name: "Tata Trusts", score: 0.9 }],
  source_url: null,
  created_at: "2026-10-20T10:00:00Z",
  ...over,
});

export const review = (over: Partial<ResearchReview> = {}): ResearchReview => ({
  slug: "kabil",
  name: "KABIL",
  kind: "funder",
  existing: false,
  answers: [],
  missing: [],
  questions: [],
  saves: [],
  ...over,
});

export const coverage = (over: Partial<ResearchCoverage> = {}): ResearchCoverage => ({
  slug: "kabil",
  stage: "planned",
  saved_at: null,
  entity: null,
  reasons: [],
  held: [],
  questions: 0,
  facts_before: null,
  facts_after: null,
  name: "KABIL",
  kind: "funder",
  years: [],
  write_checked: true,
  cells: 0,
  found: 0,
  fields_filled: 0,
  fields_total: 0,
  concepts: [],
  ...over,
});
