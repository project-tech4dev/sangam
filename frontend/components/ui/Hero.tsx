import type { ReactNode } from "react";
import { initialsOf } from "./primitives";

/* An entity's header: initials mark, kicker, name, blurb, then whatever the page adds (facets, a summary, CTAs). */
export function Hero({
  name,
  kicker,
  blurb,
  children,
  cta,
}: {
  name: string;
  kicker?: string;
  blurb?: string | null;
  children?: ReactNode;
  cta?: ReactNode;
}) {
  return (
    <header className="profile-hero">
      <div className="profile-hero-mark" aria-hidden="true">{initialsOf(name)}</div>
      <div className="profile-hero-main">
        {kicker && <div className="profile-hero-kicker">{kicker}</div>}
        <h1>{name}</h1>
        {blurb && <p className="profile-hero-desc">{blurb}</p>}
        {children}
        {cta && <div className="profile-hero-cta">{cta}</div>}
      </div>
    </header>
  );
}
