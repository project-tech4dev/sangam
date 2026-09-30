import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Badge } from "./badge";
import { Button } from "./button";
import { EntityMark } from "./primitives";

const HERO_BG: Record<string, string> = {
  "org-full": "bg-sage-800",
  "org-partial": "bg-terracotta-800",
  funder: "bg-sage-900",
};

/** A chip on the hero's dark ground. */
export function HeroChip({ children }: { children: ReactNode }) {
  return (
    <Badge variant="outline" className="border-background/25 bg-background/15 text-background">
      {children}
    </Badge>
  );
}

/** The hero's call to action, on the same dark ground. */
export function HeroAction({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Button asChild className="bg-background/15 text-background hover:bg-background/25 hover:no-underline">
      <Link href={href}>{children}</Link>
    </Button>
  );
}

export function Hero({
  kind,
  kicker,
  name,
  blurb,
  chips,
  cta,
}: {
  kind: "org-full" | "org-partial" | "funder";
  kicker?: string;
  name: string;
  blurb?: string | null;
  chips?: ReactNode;
  cta?: ReactNode;
}) {
  return (
    <section className={cn("flex flex-wrap items-start gap-6 rounded-xl p-8 text-background", HERO_BG[kind])}>
      <EntityMark name={name} size={64} />
      <div className="flex min-w-65 flex-1 flex-col gap-2.5">
        {kicker && <div className="eyebrow text-background/75">{kicker}</div>}
        <h1 className="text-2xl">{name}</h1>
        {blurb && <p className="m-0 max-w-160 text-sm text-background/85">{blurb}</p>}
        {chips && <div className="mt-1 flex flex-wrap gap-2">{chips}</div>}
      </div>
      {cta}
    </section>
  );
}
