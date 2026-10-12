"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { Tag } from "@/components/ui";
import type { Story, StoryEntity } from "@/lib/api";
import { shortDate } from "@/lib/format";

export const TOPIC_LABEL: Record<string, string> = {
  fcra: "FCRA", csr_funding: "CSR trends", ngo_news: "NGO news", programme: "Programmes", governance: "Governance",
  other: "Other",
};
const STANCE: Record<string, ["accent-2" | "neutral" | "accent", string]> = {
  positive: ["accent-2", "Positive"], neutral: ["neutral", "Neutral"], negative: ["accent", "Negative"],
};
const LEVEL_TONE: Record<string, "accent-2" | "neutral" | "accent"> = { High: "accent-2", Medium: "neutral", Low: "accent" };

const profileHref = (e: StoryEntity) => (e.kind === "org" ? `/registry/${e.slug}` : `/registry/funders/${e.slug}`);

/* One story: who or what it is about, its main source, copies folded in; scores show only signed in. */
export function StoryCard({
  story,
  about,
  signedIn = true,
  onHide,
}: {
  story: Story;
  about?: "org" | "funder";
  signedIn?: boolean;
  onHide?: (entity: StoryEntity) => void;
}) {
  // A row in the org or funder bucket is one entity's link: lead with that entity and its stance.
  const entities = about ? (story.about ? [story.about] : story.entities.filter((e) => e.kind === about)) : [];
  const stance = (about ? entities[0]?.stance : story.sentiment) ?? "neutral";
  const [tone, label] = STANCE[stance] ?? STANCE.neutral;
  const onPublic = entities.some((e) => e.visibility === "public");
  return (
    <article className="story-card">
      <div className="story-top">
        {about ? (
          entities.map((e) => (
            <Link key={e.id} className="story-chip" href={profileHref(e)} title="Open the profile">
              {e.name}
            </Link>
          ))
        ) : (
          <>
            <Tag tone="outline">{TOPIC_LABEL[story.topic] ?? story.topic}</Tag>
            {story.area_reason && <Tag tone="neutral">{story.area_reason}</Tag>}
          </>
        )}
        <Tag tone={tone}>{label}</Tag>
        {signedIn && onPublic && <Tag tone="outline">On public profile</Tag>}
      </div>
      <h3 className="story-title">
        {story.main_url ? (
          <a href={story.main_url} target="_blank" rel="noopener noreferrer">
            {story.headline}
          </a>
        ) : (
          story.headline
        )}
      </h3>
      <div className="story-meta">
        {[
          story.main_host,
          story.source_type,
          story.headline_generated ? "Headline written by Sangam" : null,
          story.published_on ? shortDate(`${story.published_on}T00:00:00`) : "No date",
          story.places.join(", ") || null,
        ]
          .filter(Boolean)
          .join(" · ")}
      </div>
      {story.summary && <p className="story-summary">{story.summary}</p>}
      {story.also.length > 0 && (
        <details className="story-also">
          <summary>
            <ChevronRight className="icon icon-sm" />
            Also reported in {story.also.length} more
          </summary>
          <ul>
            {story.also.map((l) => (
              <li key={l.url}>
                <a href={l.url} target="_blank" rel="noopener noreferrer">
                  {l.host}
                </a>{" "}
                · {l.source_type}
              </li>
            ))}
          </ul>
        </details>
      )}
      {signedIn && (
        <div className="story-act">
          <span className="muted">Match</span>
          <Tag tone={LEVEL_TONE[story.match_level] ?? "neutral"}>{story.match_level}</Tag>
          <span className="muted">Confidence</span>
          <Tag tone={LEVEL_TONE[story.confidence_level] ?? "neutral"}>{story.confidence_level}</Tag>
          {onHide &&
            entities.map((e) => (
              <button key={e.id} type="button" className="btn btn-ghost story-hide" onClick={() => onHide(e)}>
                Hide: wrong match{entities.length > 1 ? ` (${e.name})` : ""}
              </button>
            ))}
        </div>
      )}
    </article>
  );
}
