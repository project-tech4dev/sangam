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
    const result = await saveResearch(slug, decisions);
    // Nothing written (a close name left unanswered): the card stays open with the reason.
    if (!result.entity) throw new Error(`Nothing was saved. ${result.reasons.join(" ")}`.trim());
    onSaved(result);
  }
  return <ReviewCard slug={slug} onDecide={decide} inline />;
}
