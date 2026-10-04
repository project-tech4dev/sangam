import Link from "next/link";
import type { ReactNode } from "react";
import { SectionIndex } from "@/components/ui/SectionIndex";
import { TABS, type TabId } from "./tabs";

/** Resources: a title, a row of tabs (one URL each), then the tab's index beside its article. */
export function ResourcesShell({ tab, children }: { tab: TabId; children: ReactNode }) {
  const current = TABS.find((t) => t.id === tab)!;
  return (
    // Spacing follows the Terms page, which shares this layout: 48 from the page header to the
    // content, 16 from a heading to what follows it, 44 between sections.
    <div className="page reading flex flex-col gap-12">
      <div className="flex flex-col gap-7">
      <div>
        <div className="eyebrow">Resources</div>
        <h1 style={{ fontSize: "var(--fs-2xl)" }}>How Sangam works</h1>
      </div>

      <nav aria-label="Resources" className="flex flex-wrap gap-1 border-x-0 border-t-0 border-b border-solid border-(--color-divider)">
        {TABS.map((t) => {
          const active = t.id === tab;
          return (
            <Link
              key={t.id}
              href={`/resources/${t.id}`}
              aria-current={active ? "page" : undefined}
              className={
                "-mb-px border-x-0 border-t-0 border-b-2 border-solid px-4 py-3 text-base font-semibold no-underline hover:no-underline " +
                (active
                  ? "border-sage-700 text-(--color-text)"
                  : "border-transparent text-(--color-neutral-700) hover:text-(--color-accent-750)")
              }
            >
              {t.label}
            </Link>
          );
        })}
      </nav>
      </div>

      <div className="grid items-start gap-14 md:grid-cols-[220px_minmax(0,1fr)]">
        <SectionIndex sections={[...current.sections]} />
        <article className="flex min-w-0 flex-col gap-4">
          {/* The tab's own headline: one step above its section headings (24 over 20). */}
          <h2 className="measure" style={{ fontSize: "var(--fs-xl)" }}>{current.blurb}</h2>
          <div className="flex flex-col gap-11">{children}</div>
        </article>
      </div>
    </div>
  );
}

/** A section of a Resources article: anchored, with an h2 the index points at. */
export function ArticleSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="flex scroll-mt-24 flex-col gap-4">
      <h3 style={{ fontSize: "var(--fs-lg)" }}>{title}</h3>
      {children}
    </section>
  );
}
