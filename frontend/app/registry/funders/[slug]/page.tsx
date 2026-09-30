import { notFound } from "next/navigation";
import { Breadcrumbs, Hero, HeroAction, HeroChip } from "@/components/ui";
import {
  apiGet, NotFoundError,
  type FunderDetail, type GrantRow, type NewsRow, type PageOf, type ScoreRow,
} from "@/lib/api";
import { FunderProfileTabs } from "@/features/registry/ProfileTabs";

export default async function FunderProfilePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  let funder: FunderDetail;
  try {
    funder = await apiGet<FunderDetail>(`/api/funders/${slug}`);
  } catch (err) {
    if (err instanceof NotFoundError) notFound();
    throw err;
  }

  const [scores, grants, news] = await Promise.all([
    apiGet<PageOf<ScoreRow>>(`/api/scores?funder=${funder.slug}&limit=50`).then((p) => p.items),
    apiGet<PageOf<GrantRow>>(`/api/grants?funder=${funder.slug}&limit=50`).then((p) => p.items),
    apiGet<PageOf<NewsRow>>(`/api/news?funder=${funder.slug}&limit=10`).then((p) => p.items),
  ]);

  return (
    <div className="page flex flex-col gap-5">
      <Breadcrumbs
        items={[
          { label: "Sangam", href: "/registry" },
          { label: "Registry", href: "/registry" },
          { label: "Funders", href: "/registry?type=funder" },
          { label: funder.name },
        ]}
      />
      <Hero
        kind="funder"
        kicker="Funder profile"
        name={funder.name}
        blurb={(funder.profile?.funding_trend as string) ?? null}
        chips={
          <>
            {funder.funder_type && <HeroChip>{funder.funder_type.replace(/_/g, " ")}</HeroChip>}
            {funder.section_135_bound != null && (
              <HeroChip>{funder.section_135_bound ? "Section 135 bound" : "Not Section-135 bound"}</HeroChip>
            )}
            {funder.website && <HeroChip>{funder.website.replace(/^https?:\/\/(www\.)?/, "")}</HeroChip>}
          </>
        }
        cta={
          <HeroAction href="/ask">Ask Sangam who fits this mandate →</HeroAction>
        }
      />
      <FunderProfileTabs funder={funder} scores={scores} grants={grants} news={news} />
    </div>
  );
}
