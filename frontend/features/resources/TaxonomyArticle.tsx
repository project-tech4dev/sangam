import { Tag } from "@/components/ui";
import { DOMAINS } from "@/features/taxonomy/data";
import { DomainSection, SharedSection } from "@/features/taxonomy/TaxonomySections";
import { ArticleSection } from "./ResourcesShell";

export function TaxonomyArticle() {
  return (
    <>
      <ArticleSection id="how-it-works" title="How the taxonomy works">
        <p className="measure m-0">
          Work is classified by what it does, in the terms funders plan with: each programme domain has
          a few themes, and each theme a handful of sub-themes. A programme, organisation, funder or call
          is tagged with one or more sub-themes, and everything else follows from them. Environment and
          Others also give a domain to CSR spend that fits no programme.
        </p>
        <dl className="m-0 grid gap-x-6 gap-y-3 md:grid-cols-[max-content_minmax(0,1fr)]">
          <dt className="font-semibold">Themes and sub-themes</dt>
          <dd className="muted measure m-0">The tags themselves: two levels, kept deliberately short.</dd>
          <dt className="font-semibold">Crosswalks</dt>
          <dd className="muted measure m-0">
            Each sub-theme carries the SDGs it reports against, the Schedule VII clause and MCA sector
            CSR filings use, and the government schemes it connects to — so tagging once gives all three.
          </dd>
          <dt className="font-semibold">Lenses</dt>
          <dd className="muted measure m-0">
            Cross-cutting qualities tagged alongside a sub-theme, such as women &amp; girls or
            climate-smart; some add an SDG.
          </dd>
          <dt className="font-semibold">Shared vocabulary</dt>
          <dd className="muted measure m-0">SDGs, population groups and the Schedule VII sectors in use.</dd>
        </dl>
        <div className="flex flex-wrap gap-2">
          {DOMAINS.map((d) => (
            <Tag key={d.domain} tone="accent-2">{d.label}</Tag>
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
