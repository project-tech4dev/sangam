"use client";

import { PillTabs } from "@/components/ui";
import { useUrlTab } from "@/lib/useUrlTab";
import type { OrgProfile } from "@/lib/api";
import { NewsSocial } from "./NewsSocial";
import { OrgFunding } from "./OrgFunding";
import { OrgOverview } from "./OrgOverview";
import { OrgPlaces } from "./OrgPlaces";
import { ResearchSources } from "./ResearchSources";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "work", label: "Programmes & places" },
  { id: "funding", label: "Funding" },
  { id: "news", label: "News & social" },
  { id: "research", label: "Research & sources" },
];
const TAB_IDS = TABS.map((t) => t.id);

export function OrgProfileTabs({ profile, name, briefHref }: { profile: OrgProfile; name: string; briefHref: string | null }) {
  const [tab, setTab] = useUrlTab(TAB_IDS);
  return (
    <div className="profile-tabs">
      <PillTabs tabs={TABS} active={tab} onPick={setTab} variant="board" label="Profile sections" />
      {tab === "overview" && <OrgOverview org={profile.org} hiddenContacts={profile.hidden_contacts} />}
      {tab === "work" && <OrgPlaces places={profile.places} programs={profile.programs} />}
      {tab === "funding" && <OrgFunding slug={profile.org.slug} name={name} funders={profile.funders} financials={profile.financials} />}
      {tab === "news" && <NewsSocial stories={profile.news} counts={profile.stories} name={name} />}
      {tab === "research" && (
        <ResearchSources documents={profile.documents} research={profile.research} briefHref={briefHref} />
      )}
    </div>
  );
}
