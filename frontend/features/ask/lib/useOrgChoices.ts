"use client";

import { useEffect, useMemo, useState } from "react";
import type { MeOut } from "@/lib/api";
import { getMe } from "./rest";

export type OrgChoice = { slug: string; name: string };

/** Staff pick from every organisation; everyone else from the ones they belong to. */
export function useOrgChoices(orgs: { slug: string; name: string }[]) {
  const [me, setMe] = useState<MeOut | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    getMe().then(setMe, (error: Error) => setProblem(error.message));
  }, []);

  const choices: OrgChoice[] = useMemo(() => {
    if (!me) return [];
    if (me.is_staff) return orgs.map(({ slug, name }) => ({ slug, name }));
    return me.memberships.map((m) => ({ slug: m.org_slug, name: m.org_name }));
  }, [me, orgs]);

  return { me, choices, problem };
}
