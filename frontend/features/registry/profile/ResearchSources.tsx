import Link from "next/link";
import type { ProfileDocument, ResearchTrail } from "@/lib/api";
import { dayMonthYear } from "@/lib/format";
import { Card, Empty, hostOf, PTag, safeHref, sourceKind, sourceLabel, SourceLink } from "./shared";

export function ResearchSources({ documents, research, briefHref }: {
  documents: ProfileDocument[]; research: ResearchTrail; briefHref: string | null;
}) {
  // A note typed into the list ("… (no result)") is not an address.
  const sources = research.sources.filter((s) => !/\s/.test(s.url) && safeHref(s.url));
  return (
    <div className="profile-tab">
      <Card
        kicker={`Documents · ${documents.length}`}
        aside={briefHref ? <Link href={briefHref} className="profile-push">Read the full brief →</Link> : undefined}
      >
        {documents.length === 0 && <Empty>No public documents on file yet.</Empty>}
        {documents.map((d) => {
          const backs = d.links
            .map((l) => [l.program_name, l.fiscal_year, l.pages.join(", ")].filter(Boolean).join(" · "))
            .filter(Boolean);
          return (
            <div key={d.id} className="profile-line">
              <div className="profile-row">
                <strong>{d.title ?? d.source_name ?? (hostOf(d.source_url) || "Untitled document")}</strong>
                {d.as_of && <PTag>{d.as_of}</PTag>}
                <SourceLink url={d.source_url} />
              </div>
              {backs.length > 0 && <span className="profile-note">Backs {[...new Set(backs)].join("; ")}</span>}
            </div>
          );
        })}
      </Card>

      <Card kicker={`Every source read · ${sources.length}`}>
        {sources.length === 0 && <Empty>No research has been run yet.</Empty>}
        {sources.map((s) => (
          <div key={s.url} className="profile-line profile-line-tight">
            <div className="profile-row">
              <a href={safeHref(s.url)!} target="_blank" rel="noopener noreferrer" className="profile-strong">{sourceLabel(s.url)} ↗</a>
              <PTag>{sourceKind(s.url)}</PTag>
              {s.first_read && <span className="muted profile-sm">first read {dayMonthYear(s.first_read)}</span>}
            </div>
            <span className="muted profile-sm profile-wrap">{s.url}</span>
          </div>
        ))}
      </Card>
    </div>
  );
}
