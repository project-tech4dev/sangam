"use client";

import { useCallback, useRef, useState } from "react";
import type { OrgListItem, PageOf, PartnerLineRow, ScoreRow } from "@/lib/api";
import { call } from "@/lib/api/rest";
import { missingCitations, type RegistryIndex } from "./citations";
import { activityEntry, orgEntry, scoreEntry } from "./indexRows";

// The backend's cap on one `ids` lookup.
const MAX_IDS = 100;

function lookup<T>(ids: number[], get: (query: string) => Promise<T[]>): Promise<T[]> {
  if (!ids.length) return Promise.resolve([]);
  return get(ids.slice(0, MAX_IDS).map((id) => `ids=${id}`).join("&")).catch(() => []);
}

/** The page's index, plus every row an answer cites that the page did not load (it holds the first 500 orgs). */
export function useCitedIndex(base: RegistryIndex): [RegistryIndex, (answer: string) => void] {
  const [index, setIndex] = useState(base);
  const asked = useRef(new Set<string>());

  const learn = useCallback(
    (answer: string) => {
      const missing = missingCitations(answer, index);
      const fresh = (kind: string, ids: number[]) => ids.filter((id) => !asked.current.has(`${kind}:${id}`));
      const org = fresh("org", missing.org);
      const score = fresh("score", missing.score);
      const activity = fresh("activity", missing.activity);
      if (!org.length && !score.length && !activity.length) return;
      for (const [kind, ids] of [["org", org], ["score", score], ["activity", activity]] as const) {
        ids.forEach((id) => asked.current.add(`${kind}:${id}`));
      }
      // A failed lookup leaves the chip saying "Organisation's record"; it is not worth an error.
      Promise.all([
        lookup<OrgListItem>(org, (q) => call<OrgListItem[]>(`/api/orgs?${q}`)),
        lookup<ScoreRow>(score, (q) => call<PageOf<ScoreRow>>(`/api/scores?limit=${MAX_IDS}&${q}`).then((p) => p.items)),
        lookup<PartnerLineRow>(activity, (q) =>
          call<PageOf<PartnerLineRow>>(`/api/partner-lines?limit=${MAX_IDS}&${q}`).then((p) => p.items),
        ),
      ]).then(([orgs, scores, lines]) => {
        if (!orgs.length && !scores.length && !lines.length) return;
        setIndex((prev) => ({
          orgs: new Map([...prev.orgs, ...orgs.map((o) => [o.id, orgEntry(o)] as const)]),
          funders: prev.funders,
          scores: new Map([...prev.scores, ...scores.map((s) => [s.id, scoreEntry(s, prev.funders.get(s.funder_id)?.slug)] as const)]),
          activities: new Map([...prev.activities, ...lines.map((l) => [l.id, activityEntry(l)] as const)]),
        }));
      });
    },
    [index],
  );

  return [index, learn];
}
