"use client";

import { useInterrupt } from "@copilotkit/react-core/v2";
import { PauseSignal } from "./PauseSignal";
import { ReviewCard, type PausedQuestion } from "./ReviewCard";

type Paused = { slug: string; questions: PausedQuestion[] };

/** The paused promote_research and its questions, or null when the interrupt is not one. */
export function pausedSave(value: unknown): Paused | null {
  let request = value;
  if (typeof request === "string") {
    try {
      request = JSON.parse(request);
    } catch {
      return null;
    }
  }
  const actions = (request as { action_requests?: Record<string, unknown>[] } | null)?.action_requests;
  const save = actions?.find((a) => a?.name === "promote_research" && Array.isArray(a?.questions));
  if (!save) return null;
  const args = (save.args ?? {}) as { slug?: unknown };
  return {
    slug: typeof args.slug === "string" ? args.slug : "",
    questions: save.questions as PausedQuestion[],
  };
}

/** Shows the Review step while the run is paused on promote_research (HumanInTheLoopMiddleware). */
export function SaveQuestions({ agentId, onPaused }: { agentId: string; onPaused: (paused: boolean) => void }) {
  return useInterrupt({
    agentId,
    renderInChat: false,
    enabled: (event) => pausedSave(event.value) !== null,
    render: ({ event, resolve }) => {
      const paused = pausedSave(event.value);
      return paused ? (
        <>
          <ReviewCard
            key={paused.slug}
            slug={paused.slug}
            questions={paused.questions}
            // The slug picks this save out when several writers are paused at once.
            onDecide={(decision) => void resolve({ decisions: [decision], slug: paused.slug })}
          />
          <PauseSignal onPaused={onPaused} />
        </>
      ) : (
        <></>
      );
    },
  });
}
