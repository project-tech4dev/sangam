"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { SECTIONS, type SectionId } from "./sections";


const OFFSET = 96;


export function TermsIndex() {
  const [active, setActive] = useState<SectionId>(SECTIONS[0][0]);

  useEffect(() => {
    const onScroll = () => {
      let current: SectionId = SECTIONS[0][0];
      for (const [id] of SECTIONS) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top < OFFSET + 44) current = id;
      }
      setActive(current);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  function go(id: SectionId) {
    const el = document.getElementById(id);
    if (!el) return;
    window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - OFFSET, behavior: "smooth" });
    setActive(id);
  }

  return (
    <nav aria-label="Sections" className="sticky top-24 hidden flex-col gap-0.5 border-l md:flex">
      {SECTIONS.map(([id, label]) => (
        <button
          key={id}
          type="button"
          onClick={() => go(id)}
          aria-current={id === active ? "true" : undefined}
          className={cn(
            "-ml-px cursor-pointer border-l-2 py-[7px] pl-4 text-left text-sm",
            id === active ? "border-sage-700 font-bold text-foreground" : "border-transparent text-sand-700",
          )}
        >
          {label}
        </button>
      ))}
    </nav>
  );
}
