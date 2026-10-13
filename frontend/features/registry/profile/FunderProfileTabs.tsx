"use client";

import { useState } from "react";
import { PillTabs } from "@/components/ui";
import type { FunderProfile } from "@/lib/api";
import { FunderGiving } from "./FunderGiving";
import { FunderMandate } from "./FunderMandate";
import { FunderReach } from "./FunderReach";
import { NewsSocial } from "./NewsSocial";
import { ResearchSources } from "./ResearchSources";

const TABS = [
  { id: "mandate", label: "Mandate" },
  { id: "giving", label: "Giving" },
  { id: "reach", label: "Reach" },
  { id: "news", label: "News & social" },
  { id: "research", label: "Research & sources" },
];

export function FunderProfileTabs({ profile, briefHref }: { profile: FunderProfile; briefHref: string | null }) {
  const [tab, setTab] = useState("mandate");
  const { funder } = profile;
  return (
    <div className="profile-tabs">
      <PillTabs tabs={TABS} active={tab} onPick={setTab} variant="board" label="Profile sections" />
      {tab === "mandate" && (
        <FunderMandate
          funder={funder} eligibility={profile.eligibility} openCalls={profile.open_calls}
          programs={profile.programs} hiddenContacts={profile.hidden_contacts}
        />
      )}
      {tab === "giving" && (
        <FunderGiving
          slug={funder.slug} spend={profile.spend} csrYears={profile.csr_years} programs={profile.programs}
          parent={funder.parent} partners={profile.partners}
        />
      )}
      {tab === "reach" && <FunderReach metrics={profile.metrics} footprint={profile.footprint} stated={profile.stated} />}
      {tab === "news" && <NewsSocial stories={profile.news} counts={profile.stories} name={funder.name} />}
      {tab === "research" && (
        <ResearchSources documents={profile.documents} research={profile.research} briefHref={briefHref} />
      )}
    </div>
  );
}
