import { Tag } from "@/components/ui";
import { DOMAINS } from "@/features/taxonomy/data";
import { DomainSection, SharedSection } from "@/features/taxonomy/TaxonomySections";
import { ArticleSection } from "./ResourcesShell";

export function TaxonomyArticle() {
  return (
    <>
      <ArticleSection id="how-it-works" title="How the taxonomy works">
        <p className="measure m-0">
          Each domain is a tree of areas and sub-areas. Every sub-area carries the SDGs and sector
          labels it maps to. Cross-cutting layers add detail without growing the tree:
        </p>
        <dl className="m-0 grid gap-x-6 gap-y-3 md:grid-cols-[max-content_minmax(0,1fr)]">
          <dt className="font-semibold">Tracks and care levels</dt>
          <dd className="muted measure m-0">
            Apply across every sub-area — occupation tracks in Livelihoods, levels of care in Health.
          </dd>
          <dt className="font-semibold">Modifiers</dt>
          <dd className="muted measure m-0">
            Added to a programme on top of its area, such as women-led or uses digital tools; some add SDGs.
          </dd>
          <dt className="font-semibold">Enabling work</dt>
          <dd className="muted measure m-0">Work that makes programmes possible rather than delivering one.</dd>
          <dt className="font-semibold">Shared vocabulary</dt>
          <dd className="muted measure m-0">SDGs, sectors and population groups, common to every domain.</dd>
        </dl>
        <div className="flex flex-wrap gap-2">
          {DOMAINS.map((d) => (
            <Tag key={d.domain} tone={d.status === "draft" ? "accent" : "accent-2"}>
              {d.label} · {d.status === "draft" ? "Draft" : "Active"}
            </Tag>
          ))}
        </div>
      </ArticleSection>
      {DOMAINS.map((d) => (
        <DomainSection key={d.domain} domain={d} />
      ))}
      <SharedSection />
    </>
  );
}
