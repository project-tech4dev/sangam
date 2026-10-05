export type CitationKind = "org" | "funder" | "grant" | "score" | "graph";

/** Where an entity's row was read from. Optional throughout: most tables record it,
 *  some rows do not, and the rail says "no source recorded" rather than hiding the gap. */
export type Provenance = { sourceUrl?: string | null; sourceName?: string | null; fetchedAt?: string | null };

export type RegistryIndex = {
  orgs: Map<number, { slug: string; name: string } & Provenance>;
  funders: Map<number, { slug: string; name: string } & Provenance>;
  scores: Map<number, { funderSlug: string; orgName: string; funderName: string; rubricVersion?: string | null }>;
  grants: Map<number, { orgSlug: string; title: string } & Provenance>;
};

const CITE_RE = /\[(org|funder|grant|score|graph):([a-zA-Z0-9]+)\]/g;

/** Rewrite [kind:id] markers into private-scheme links, skipping code spans. */
export function linkifyCitations(md: string): string {
  return md
    .split(/(```[\s\S]*?```|`[^`]*`)/g)
    .map((segment, i) =>
      i % 2 === 1 ? segment : segment.replace(CITE_RE, (_, kind, id) => `[${kind}:${id}](sangam://${kind}/${id})`),
    )
    .join("");
}

export function extractCitations(text: string): { kind: CitationKind; id: string }[] {
  const seen = new Set<string>();
  const out: { kind: CitationKind; id: string }[] = [];
  for (const match of text.matchAll(CITE_RE)) {
    const key = `${match[1]}:${match[2]}`;
    if (!seen.has(key)) {
      seen.add(key);
      out.push({ kind: match[1] as CitationKind, id: match[2]! });
    }
  }
  return out;
}

export function citationTarget(
  kind: CitationKind,
  id: string,
  index: RegistryIndex | null,
): { href: string | null; label: string } {
  const numeric = Number(id);
  switch (kind) {
    case "org": {
      const org = index?.orgs.get(numeric);
      return { href: `/registry/${org?.slug ?? id}`, label: org?.name ?? `org #${id}` };
    }
    case "funder": {
      const funder = index?.funders.get(numeric);
      return { href: `/registry/funders/${funder?.slug ?? id}`, label: funder?.name ?? `funder #${id}` };
    }
    case "score": {
      const score = index?.scores.get(numeric);
      return {
        href: score ? `/registry/funders/${score.funderSlug}` : null,
        label: score ? `${score.orgName} × ${score.funderName}` : `score #${id}`,
      };
    }
    case "grant": {
      const grant = index?.grants.get(numeric);
      return { href: grant ? `/registry/${grant.orgSlug}` : null, label: grant?.title ?? `grant #${id}` };
    }
    case "graph":
      return { href: null, label: `graph evidence ${id.slice(0, 8)}` };
  }
}
