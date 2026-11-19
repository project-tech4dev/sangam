/* The Registry's paged list, read from the browser as the person scrolls or filters. */

import type { RegistryPage } from "@/lib/api";
import { call } from "@/lib/api/rest";

export const fetchRegistryPage = (query: string) => call<RegistryPage>(`/api/registry?${query}`);

/** Staff: every organisation a change check can run on; anyone else is refused, which reads as none. */
export type Tracked = { slug: string; kind: "org" | "funder"; sources: number; last_checked: string | null };
export const fetchTracked = () => call<Tracked[]>("/api/ingest/tracked").catch(() => [] as Tracked[]);
