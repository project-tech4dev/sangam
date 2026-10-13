import { notFound, permanentRedirect } from "next/navigation";
import { Breadcrumbs } from "@/components/ui";
import { apiGet, NotFoundError, type FunderProfile } from "@/lib/api";
import { displayName, funderTypeLabel } from "@/lib/format";
import { latestFootprint } from "@/features/registry/profile/FunderReach";
import { FunderProfileTabs } from "@/features/registry/profile/FunderProfileTabs";
import { ProfileHero } from "@/features/registry/profile/ProfileHero";
import { count } from "@/features/registry/profile/shared";

export default async function FunderProfilePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  let profile: FunderProfile;
  try {
    profile = await apiGet<FunderProfile>(`/api/funders/${slug}/profile`);
  } catch (err) {
    if (err instanceof NotFoundError) notFound();
    throw err;
  }
  // A funder asked for by id lives at its slug; redirect throws, so it stays outside the try.
  if (profile.funder.slug !== slug) permanentRedirect(`/registry/funders/${profile.funder.slug}`);
  const { funder, brief } = profile;
  const name = displayName(funder.name);

  const kicker = [
    "Funder",
    funder.funder_type && funderTypeLabel(funder.funder_type).toLowerCase(),
    [funder.legal_form?.toLowerCase(), funder.founded_year].filter(Boolean).join(", "),
    funder.parent && `of ${funder.parent.name}`,
  ].filter(Boolean).join(" · ");
  const fp = latestFootprint(profile.footprint);
  const line = [
    fp.states > 0 && (fp.districts > 0
      ? `Projects in ${count(fp.districts, "district")} across ${count(fp.states, "state")} (${fp.year})`
      : `Projects in ${count(fp.states, "state")} (${fp.year})`),
    profile.partners.total > 0 && count(profile.partners.total, "named partner"),
  ].filter((x): x is string => !!x);

  const briefHref = brief ? `/registry/funders/${funder.slug}/brief` : null;

  return (
    <div className="page profile-page">
      <Breadcrumbs
        items={[
          { label: "Registry", href: "/registry" },
          { label: "Funders", href: "/registry?type=funder" },
          { label: name },
        ]}
      />
      <ProfileHero
        name={name}
        kicker={kicker}
        description={funder.funding_trend}
        tags={profile.tags}
        sdgs={profile.sdgs}
        whoLabel="Who it funds for"
        line={line}
        website={funder.website}
        ask={{
          href: `/ask?q=${encodeURIComponent(`Which NGOs in the base fit ${name}'s mandate, and why?`)}`,
          label: "Ask who fits this mandate →",
        }}
        brief={briefHref}
      />
      <FunderProfileTabs profile={profile} briefHref={briefHref} />
    </div>
  );
}
