"use client";

import { useEffect } from "react";

/** Tells the workspace a question card is open, for as long as it is mounted. */
export function PauseSignal({ onPaused }: { onPaused: (paused: boolean) => void }) {
  useEffect(() => {
    onPaused(true);
    return () => onPaused(false);
  }, [onPaused]);
  return null;
}
