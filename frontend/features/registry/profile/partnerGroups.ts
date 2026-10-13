"use client";

import { useState } from "react";
import type { PartnerGroup, PartnerGroupPage, PartnerLineRow } from "@/lib/api";
import { authHeaders } from "@/lib/api/auth-headers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

/* A profile's partner groups: the first page came with the profile, the rest load as the reader scrolls. */
export function usePartnerGroups(first: PartnerGroupPage, path: string) {
  const [state, setState] = useState({ groups: first.groups, next: first.next_cursor, busy: false, error: false });
  const more = () => {
    if (!state.next || state.busy) return;
    const cursor = state.next;
    setState((s) => ({ ...s, busy: true }));
    authHeaders()
      .then((headers) => fetch(`${API}${path}?cursor=${encodeURIComponent(cursor)}`, { headers }))
      .then((res) => (res.ok ? (res.json() as Promise<PartnerGroupPage>) : Promise.reject(new Error(String(res.status)))))
      .then(
        (page) => setState((s) => ({ groups: [...s.groups, ...page.groups], next: page.next_cursor, busy: false, error: false })),
        () => setState((s) => ({ ...s, busy: false, error: true })),
      );
  };
  return { groups: state.groups, busy: state.busy, error: state.error, more };
}

/* The year a line is shown under; an undated line has none. */
export const lineYear = (l: PartnerLineRow) =>
  l.fy_is_dated ? l.fiscal_year : l.start_date ? `FY${l.start_date.slice(0, 4)}` : "";

/* Two catalog rows saying the same thing (year, project, amount) show once. */
export function distinctLines(group: PartnerGroup): PartnerLineRow[] {
  const seen = new Set<string>();
  return group.lines.filter((l) => {
    const key = `${lineYear(l)}|${l.project_name ?? l.program_name ?? ""}|${l.amount ?? ""}|${l.relationship_status ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
