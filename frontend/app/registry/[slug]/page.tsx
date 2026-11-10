import { notFound, permanentRedirect } from "next/navigation";
import { Breadcrumbs } from "@/components/ui";
import { apiGet, NotFoundError, type OrgProfile } from "@/lib/api";
import { displayName, monthYear, titleCase } from "@/lib/format";
import { placeGroups } from "@/features/registry/profile/OrgPlaces";
import { OrgProfileTabs } from "@/features/registry/profile/OrgProfileTabs";
import { ProfileHero } from "@/features/registry/profile/ProfileHero";
import { count } from "@/features/registry/profile/shared";

export default async function OrgProfilePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  let profile: OrgProfile;
  try {
    profile = await apiGet<OrgProfile>(`/api/orgs/${slug}/profile`);
  } catch (err) {
    if (err instanceof NotFoundError) notFound();
    throw err;
  }
  // An org asked for by id lives at its slug; redirect throws, so it stays outside the try.
  if (profile.org.slug !== slug) permanentRedirect(`/registry/${profile.org.slug}`);
  const { org } = profile;
  const name = displayName(org.name);

  const registered = monthYear(org.registration_date, true);
  const kicker = ["CSO", org.legal_form, registered && `registered ${registered}`].filter(Boolean).join(" · ");
  const { districts, states } = placeGroups(profile.places);
  const office = profile.places.find((p) => p.role === "registered")?.name ?? org.district ?? org.state;
  const line = [
    office && `Registered office ${titleCase(office)}`,
    states > 0 && `works in ${count(states, "state")}, ${count(districts, "district")}`,
  ].filter((x): x is string => !!x);

  const briefHref = profile.brief ? `/registry/${org.slug}/brief` : null;

  return (
    <div className="page profile-page">
      <Breadcrumbs
        items={[
          { label: "Registry", href: "/registry" },
          { label: "CSOs", href: "/registry?type=cso" },
          { label: name },
        ]}
      />
      <ProfileHero
        name={name}
        kicker={kicker}
        description={org.description}
        tags={profile.tags}
        sdgs={profile.sdgs}
        whoLabel="Who it serves"
        line={line}
        website={org.website}
        ask={{
          href: `/ask?q=${encodeURIComponent(`What does ${name} do, where does it work, and which funders fit it?`)}`,
          label: `Ask Sangam about ${name} →`,
        }}
        brief={briefHref}
      />
      <OrgProfileTabs profile={profile} name={name} briefHref={briefHref} />
    </div>
  );
}
