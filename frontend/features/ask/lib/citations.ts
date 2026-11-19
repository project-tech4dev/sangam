export type CitationKind = "org" | "funder" | "activity" | "grant" | "score" | "news" | "graph";

/** Where an entity's row was read from. Optional throughout: most tables record it,
 *  some rows do not, and the rail says "no source recorded" rather than hiding the gap. */
export type Provenance = { sourceUrl?: string | null; sourceName?: string | null; fetchedAt?: string | null };

export type RegistryIndex = {
  orgs: Map<number, { slug: string; name: string } & Provenance>;
  funders: Map<number, { slug: string; name: string } & Provenance>;
  scores: Map<number, { funderSlug: string; orgName: string; funderName: string; rubricVersion?: string | null }>;
  activities: Map<number, { href: string; title: string; short?: string } & Provenance>;
};

const CITE_RE = /\[(org|funder|activity|grant|score|news|graph):([a-zA-Z0-9]+)\]/g;

// How far back, on the same line or table cell, a name counts as already written beside its marker.
const NAMED_WINDOW = 120;

function alreadyNamed(before: string, name: string | undefined): boolean {
  if (!name) return false;
  const lineStart = Math.max(before.lastIndexOf("\n"), before.lastIndexOf("|")) + 1;
  const near = before.slice(Math.max(lineStart, before.length - NAMED_WINDOW)).replace(/[*_`]/g, "");
  return near.toLowerCase().includes(name.toLowerCase());
}

/** Rewrite [kind:id] markers into private-scheme links, skipping code spans. A marker right after its
 *  entity's name gets `?named`, so the chip says "source" instead of repeating the name. */
export function linkifyCitations(md: string, index: RegistryIndex | null = null): string {
  return md
    .split(/(```[\s\S]*?```|`[^`]*`)/g)
    .map((segment, i) =>
      i % 2 === 1
        ? segment
        : segment.replace(CITE_RE, (_, kind: string, id: string, offset: number) => {
            const name =
              kind === "org" ? index?.orgs.get(Number(id))?.name : kind === "funder" ? index?.funders.get(Number(id))?.name : undefined;
            const flag = alreadyNamed(segment.slice(0, offset), name) ? "?named" : "";
            return `[${kind}:${id}](sangam://${kind}/${id}${flag})`;
          }),
    )
    .join("");
}

/** What a chip says: the entity's name, or a plain word when the page does not hold the row. Never a code. */
export function chipText(kind: CitationKind, id: string, index: RegistryIndex | null): string {
  const numeric = Number(id);
  switch (kind) {
    case "org":
      return index?.orgs.get(numeric)?.name ?? "Organisation's record";
    case "funder":
      return index?.funders.get(numeric)?.name ?? "Funder's record";
    case "score": {
      const score = index?.scores.get(numeric);
      return score ? `${score.orgName} × ${score.funderName}` : "Funder Match";
    }
    case "activity": {
      const line = index?.activities.get(numeric);
      return line?.short ?? line?.title ?? "Funding record";
    }
    case "grant":
      return "Past grant";
    case "news":
      return "News";
    case "graph":
      return "Sangam's links";
  }
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
    case "activity": {
      // The index holds partner lines only; a spend or footprint line renders unlinked under its number.
      const line = index?.activities.get(numeric);
      return { href: line?.href ?? null, label: line?.title ?? `funder activity #${id}` };
    }
    case "grant":
      // Retired in 0034; a saved thread's marker shows as a chip, unlinked, rather than as raw brackets.
      return { href: null, label: `grant #${id} (retired)` };
    case "news":
      // No story page yet; the answer names the headline beside the marker.
      return { href: null, label: `news story #${id}` };
    case "graph":
      return { href: null, label: `graph evidence ${id.slice(0, 8)}` };
  }
}
