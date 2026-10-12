import Link from "next/link";
import { notFound } from "next/navigation";
import { Breadcrumbs, Hero, Tag } from "@/components/ui";
import { apiGet, NotFoundError, type FunderProfile } from "@/lib/api";
import { FunderProfileTabs } from "@/features/registry/ProfileTabs";

export default async function FunderProfilePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  let profile: FunderProfile;
  try {
    profile = await apiGet<FunderProfile>(`/api/funders/${slug}/profile`);
  } catch (err) {
    if (err instanceof NotFoundError) notFound();
    throw err;
  }
  const { funder, scores, partners, news, brief } = profile;

  return (
    <div className="page profile-page">
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
            {funder.funder_type && <Tag tone="ondark">{funder.funder_type.replace(/_/g, " ")}</Tag>}
            {funder.section_135_bound != null && (
              <Tag tone="ondark">{funder.section_135_bound ? "Section 135 bound" : "Not Section-135 bound"}</Tag>
            )}
            {funder.website && <Tag tone="ondark">{funder.website.replace(/^https?:\/\/(www\.)?/, "")}</Tag>}
          </>
        }
        cta={
          <div className="profile-cta">
            <Link
              href={`/ask?q=${encodeURIComponent(`Which NGOs in the base fit ${funder.name}'s mandate, and why?`)}`}
              className="btn btn-ondark">
              Ask Sangam who fits this mandate →
            </Link>
            {brief && (
              <Link href={`/registry/funders/${slug}/brief`} className="btn btn-ondark">
                Research brief →
              </Link>
            )}
          </div>
        }
      />
      <FunderProfileTabs
        funder={funder} scores={scores} partners={partners.items} partnersTotal={partners.total} news={news}
      />
    </div>
  );
}
