"use client";

import { useEffect, useMemo, useState } from "react";
import type { MeOut } from "@/lib/api";
import { getMe } from "./rest";

export type OrgChoice = { slug: string; name: string };

/** Staff pick from every organisation; everyone else from the ones they belong to. Asks /api/me only without `seed`. */
export function useOrgChoices(orgs: { slug: string; name: string }[], seed: MeOut | null = null) {
  const [me, setMe] = useState<MeOut | null>(seed);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (seed) return;
    getMe().then(setMe, (error: Error) => setProblem(error.message));
  }, [seed]);

  const choices: OrgChoice[] = useMemo(() => {
    if (!me) return [];
    if (me.is_staff) return orgs.map(({ slug, name }) => ({ slug, name }));
    return me.memberships.map((m) => ({ slug: m.org_slug, name: m.org_name }));
  }, [me, orgs]);

  return { me, choices, problem };
}
