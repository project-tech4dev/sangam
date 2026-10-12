"use client";

import type { Story } from "@/lib/api";
import { StoryCard } from "@/features/ask/views/media/StoryCard";

// Read as a calendar date, not UTC midnight, so the 1st never slips into the month before.
const month = (s: Story) =>
  s.published_on
    ? new Date(`${s.published_on}T00:00:00`).toLocaleDateString("en-IN", { month: "long", year: "numeric" })
    : "Undated";

/* A profile's public stories by month, the same signed in or out; the rest live in Media & Signals. */
export function InTheNews({ stories, kind, name }: { stories: Story[]; kind: "org" | "funder"; name: string }) {
  if (stories.length === 0) return <p className="muted">No stories about {name} clear the public bar yet.</p>;
  return (
    <div className="story-list">
      {stories.map((s, i) => (
        <div key={s.row_id} className="story-list">
          {(i === 0 || month(stories[i - 1]) !== month(s)) && <div className="story-month">{month(s)}</div>}
          <StoryCard story={s} about={kind} signedIn={false} />
        </div>
      ))}
    </div>
  );
}
