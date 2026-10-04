"use client";

import { useEffect, useState } from "react";
import type React from "react";
import { cn } from "@/lib/utils";

// Clears the sticky navbar plus a little air when jumping to a section.
const OFFSET = 96;

export type IndexEntry = { id: string; label: string; sub?: boolean };

/**
 * "In this article": a sticky list of a page's sections that highlights the one in view
 * and scrolls to a section on click. Hidden below md, where the page simply scrolls.
 *
 * Entries are plain links to #section, not buttons: a link carries no browser box, so the
 * index looks the same on Terms (inside the `.sangam-ui` reset) and on Resources (outside it).
 */
export function SectionIndex({ sections, title }: { sections: IndexEntry[]; title?: string }) {
  const [active, setActive] = useState(sections[0]?.id);

  useEffect(() => {
    const onScroll = () => {
      let current = sections[0]?.id;
      for (const { id } of sections) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top < OFFSET + 44) current = id;
      }
      setActive(current);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [sections]);

  function go(event: React.MouseEvent, id: string) {
    const el = document.getElementById(id);
    if (!el) return;
    event.preventDefault();
    window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - OFFSET, behavior: "smooth" });
    window.history.replaceState(null, "", `#${id}`);
    setActive(id);
  }

  return (
    <nav aria-label={title ?? "Sections"} className="sticky top-24 hidden flex-col gap-0.5 md:flex">
      {title && <div className="mb-2 text-xs font-bold tracking-[0.12em] text-sand-700 uppercase">{title}</div>}
      <div className="flex flex-col gap-0.5 border-l border-solid border-(--color-divider)">
        {sections.map(({ id, label, sub }) => (
          <a
            key={id}
            href={`#${id}`}
            onClick={(event) => go(event, id)}
            aria-current={id === active ? "true" : undefined}
            className={cn(
              "-ml-px border-y-0 border-r-0 border-l-2 border-solid py-[7px] text-sm leading-snug no-underline hover:no-underline",
              sub ? "pl-7" : "pl-4",
              id === active
                ? "border-sage-700 font-bold text-foreground"
                : "border-transparent text-sand-700 hover:text-foreground",
            )}
          >
            {label}
          </a>
        ))}
      </div>
    </nav>
  );
}
