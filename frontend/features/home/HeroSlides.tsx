"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const SLIDES = [
  {
    who: "For NGOs",
    line: "Find the funders who fit your work",
    outputs: [
      "Funder shortlist, scored on each funder’s rubric",
      "Open calls matched to your programs, weekly",
      "Draft feedback before you submit",
    ],
  },
  {
    who: "For funders",
    line: "See which NGOs match your mandate",
    outputs: [
      "NGOs ranked against your mandate, with reasons",
      "Diligence gaps flagged per organisation",
      "Media coverage to affirm or question",
    ],
  },
  {
    who: "For ecosystem players",
    line: "Spot the gaps, refer the right partners",
    outputs: [
      "Funding gaps by state and sector",
      "NGOs worth referring into your networks",
      "One shared rubric across programmes",
    ],
  },
] as const;

const INTERVAL_MS = 8000;

/** The hero's use-case panel: fades between slides every 8s, pauses on hover. */
export function HeroSlides() {
  const [current, setCurrent] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused) return;
    const timer = setInterval(() => setCurrent((i) => (i + 1) % SLIDES.length), INTERVAL_MS);
    return () => clearInterval(timer);
  }, [paused]);

  return (
    <div onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
      <div className="relative h-80 overflow-hidden rounded-lg bg-background shadow-[var(--shadow-md)]">
        {SLIDES.map((slide, i) => (
          <div
            key={slide.who}
            aria-hidden={i !== current}
            className={cn(
              "absolute inset-0 flex flex-col transition-[opacity,transform] duration-[1200ms] ease-in-out",
              i === current ? "opacity-100" : "pointer-events-none translate-y-2 opacity-0",
            )}
          >
            <div className="flex h-full flex-col justify-center gap-1.5 px-8 pt-8 pb-7">
              <Badge
                variant="secondary"
                className="self-start rounded-md px-2.5 py-[3px] font-normal tracking-[0.02em]"
              >
                {slide.who}
              </Badge>
              <div className="mb-2.5 text-2xl leading-[1.2]">{slide.line}</div>
              {slide.outputs.map((output) => (
                <div key={output} className="flex items-center gap-2.5 border-t py-1.5 text-sm">
                  <span className="size-2 flex-none rounded-full bg-primary" />
                  <span>{output}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 flex items-center gap-3.5">
        {SLIDES.map((slide, i) => (
          <button
            key={slide.who}
            type="button"
            aria-label={slide.who}
            onClick={() => setCurrent(i)}
            className={cn(
              "h-2.5 cursor-pointer rounded-md transition-[width,background-color] duration-300",
              i === current ? "w-[34px] bg-primary" : "w-2.5 bg-sand-300",
            )}
          />
        ))}
        <span className="ml-auto text-sm text-sand-700">
          {current + 1} / {SLIDES.length}
        </span>
      </div>
    </div>
  );
}
