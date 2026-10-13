import Link from "next/link";
import { Hero } from "@/components/ui";
import type { SdgRef, TagNote } from "@/lib/api";
import { SDG_NAME, SDG_SHORT } from "../sdg";
import { safeHref, splitTags, themeLabel } from "./shared";

/* The shared Hero, filled as the boards draw a profile: tags beside their labels, a summary line, then the CTAs. */
export function ProfileHero({
  name, kicker, description, tags, sdgs, whoLabel, line, website, ask, brief,
}: {
  name: string; kicker: string; description: string | null; tags: TagNote[]; sdgs: SdgRef[];
  whoLabel: string; line: string[]; website: string | null;
  ask: { href: string; label: string }; brief: string | null;
}) {
  const { themes, who } = splitTags(tags);
  const href = safeHref(website);
  return (
    <Hero
      name={name}
      kicker={kicker}
      blurb={description}
      cta={
        <>
          <Link href={ask.href} className="profile-cta-primary">{ask.label}</Link>
          {brief && <Link href={brief} className="profile-cta-secondary">Read the research brief</Link>}
        </>
      }
    >
      {(themes.length > 0 || who.length > 0 || sdgs.length > 0) && (
        <dl className="profile-hero-facets">
          {themes.length > 0 && (
            <>
              <dt className="profile-hero-label">Themes</dt>
              <dd className="profile-hero-pills">
                {themes.map((t) => <span key={t.slug} className="profile-theme" title={themeLabel(t)}>{t.label}</span>)}
              </dd>
            </>
          )}
          {who.length > 0 && (
            <>
              <dt className="profile-hero-label">{whoLabel}</dt>
              <dd className="profile-hero-pills">
                {who.map((t) => <span key={t.slug} className="profile-lens">{t.label}</span>)}
              </dd>
            </>
          )}
          {sdgs.length > 0 && (
            <>
              <dt className="profile-hero-label">SDGs</dt>
              <dd className="profile-hero-pills">
                {sdgs.map((g) => {
                  const short = SDG_SHORT[g.code] ?? g.label;
                  return (
                    <a key={g.code} className="profile-sdg" data-sdg={g.code} title={`SDG ${g.code}: ${SDG_NAME[g.code] ?? short}, through its themes`}
                      aria-label={`SDG ${g.code}: ${SDG_NAME[g.code] ?? short}`}
                      href={`https://sdgs.un.org/goals/goal${g.code}`} target="_blank" rel="noopener noreferrer">
                      <span className="profile-sdg-n">{g.code}</span>
                      <span className="profile-sdg-l">{short}</span>
                    </a>
                  );
                })}
              </dd>
            </>
          )}
        </dl>
      )}
      {(line.length > 0 || href) && (
        <div className="profile-hero-line">
          {line.join(" · ")}
          {href && (
            <>
              {line.length > 0 && " · "}
              <a href={href} target="_blank" rel="noopener noreferrer">
                {href.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")} ↗
              </a>
            </>
          )}
        </div>
      )}
    </Hero>
  );
}
