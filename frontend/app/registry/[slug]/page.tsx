import { notFound } from "next/navigation";
import { Breadcrumbs, Hero, HeroAction, HeroChip } from "@/components/ui";
import {
  apiGet, NotFoundError,
  type GrantRow, type NewsRow, type OrgDetail, type PageOf, type ProgramRow, type ScoreRow,
} from "@/lib/api";
import { titleCase } from "@/lib/format";
import { OrgProfileTabs } from "@/features/registry/ProfileTabs";

export default async function OrgProfilePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  let org: OrgDetail;
  try {
    org = await apiGet<OrgDetail>(`/api/orgs/${slug}`);
  } catch (err) {
    if (err instanceof NotFoundError) notFound();
    throw err;
  }

  const [grants, programs, scores, news] = await Promise.all([
    apiGet<PageOf<GrantRow>>(`/api/grants?org=${org.slug}&limit=50`).then((p) => p.items),
    apiGet<PageOf<ProgramRow>>(`/api/programs?org=${org.slug}&limit=50`).then((p) => p.items),
    apiGet<PageOf<ScoreRow>>(`/api/scores?org=${org.slug}&limit=50`).then((p) => p.items),
    apiGet<PageOf<NewsRow>>(`/api/news?org=${org.slug}&limit=10`).then((p) => p.items),
  ]);

  const isFull = org.identifiers.length >= 4;
  const displayName = titleCase(org.name);

  return (
    <div className="page flex flex-col gap-5">
      <Breadcrumbs
        items={[
          { label: "Sangam", href: "/registry" },
          { label: "Registry", href: "/registry" },
          { label: org.state ?? "India" },
          { label: displayName },
        ]}
      />
      <Hero
        kind={isFull ? "org-full" : "org-partial"}
        kicker={org.legal_form ?? "Civil-society organisation"}
        name={displayName}
        blurb={
          org.registration_date
            ? `Registered ${new Date(org.registration_date).toLocaleDateString("en-IN", { year: "numeric", month: "long" })}${org.district ? ` · ${titleCase(org.district)}, ${org.state}` : ""}`
            : null
        }
        chips={
          <>
            <HeroChip>{isFull ? "Base coverage — good" : "Base coverage — partial"}</HeroChip>
            {["fcra", "80g", "12a", "csr1"].map((idType) => {
              const has = org.identifiers.some((i) => i.id_type === idType);
              return (
                <HeroChip key={idType}>
                  {idType.toUpperCase()} — {has ? "on file" : "not entered"}
                </HeroChip>
              );
            })}
          </>
        }
        cta={
          <HeroAction href="/ask">Ask Sangam about this CSO →</HeroAction>
        }
      />
      <OrgProfileTabs org={org} grants={grants} programs={programs} scores={scores} news={news} />
    </div>
  );
}
