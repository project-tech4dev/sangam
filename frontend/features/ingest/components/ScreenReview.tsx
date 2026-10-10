"use client";

import { saveResearch, type SaveResult } from "../lib/saveActions";
import { ReviewCard, type SaveDecision } from "./ReviewCard";

/** The Review card for one organisation, saved straight from the screen rather than through a paused agent. */
export function ScreenReview({
  slug,
  onSaved,
  onDeclined,
}: {
  slug: string;
  onSaved: (result: SaveResult) => void;
  onDeclined: () => void;
}) {
  async function decide(decision: SaveDecision) {
    if (decision.type === "reject") return onDeclined();
    const decisions = (decision.edited_action.args.decisions ?? {}) as Record<string, string>;
    onSaved(await saveResearch(slug, decisions));
  }
  return <ReviewCard slug={slug} onDecide={decide} inline />;
}
