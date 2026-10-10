"use client";

import { useEffect, useRef, useState } from "react";
import { useInterrupt } from "@copilotkit/react-core/v2";
import type { ImportAccess, VaultFile } from "../lib/access";
import { EMPTY_SOURCES, nothingChosen, proposedSources, sourcesDecision, type SourcesChoice } from "../lib/sourcePick";
import { PauseSignal } from "./PauseSignal";
import { SourcePicker } from "./SourcePicker";

/** Where should Sangam read from? Asked mid-run only when the Start step did not already answer it. */
function Card({
  access,
  vaultFiles,
  onDecide,
}: {
  access: ImportAccess;
  vaultFiles: VaultFile[];
  onDecide: (choice: SourcesChoice) => void;
}) {
  const [choice, setChoice] = useState<SourcesChoice>(EMPTY_SOURCES);
  const [sent, setSent] = useState(false);

  function decide(next: SourcesChoice) {
    setSent(true);
    onDecide(next);
  }

  return (
    <section className="import-pick" aria-label="Where Sangam reads from">
      <div className="import-head">
        <span className="card-kicker">Sangam needs your answer</span>
        <strong className="import-pick-title">Where should Sangam read from?</strong>
        <span className="import-pick-text">Nothing is opened until you choose. Sangam reads only what you tick.</span>
      </div>

      <SourcePicker
        value={choice}
        onChange={setChoice}
        staff={access.staff}
        vaultFiles={vaultFiles}
        showOrg={access.orgs.length > 1}
        disabled={sent}
      />

      <div className="import-pick-actions">
        <button type="button" className="btn btn-primary" onClick={() => decide(choice)} disabled={sent || nothingChosen(choice)}>
          Start reading
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => decide({ ...EMPTY_SOURCES, web: true })}
          disabled={sent}
        >
          Only public websites
        </button>
      </div>
    </section>
  );
}

/** Answers the pause with what the person ticked on the Start step, so they are not asked twice. */
function AutoAnswer({ preset, onDecide }: { preset: SourcesChoice; onDecide: (choice: SourcesChoice) => void }) {
  const sent = useRef(false);
  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    onDecide(preset);
  }, [preset, onDecide]);
  return null;
}

/** Shows the sources question while the run is paused on choose_sources, unless `preset` answers it. */
export function SourcesCard({
  agentId,
  access,
  vaultFiles,
  preset,
  onPaused,
}: {
  agentId: string;
  access: ImportAccess;
  vaultFiles: VaultFile[];
  preset: SourcesChoice | null;
  onPaused: (paused: boolean) => void;
}) {
  return useInterrupt({
    agentId,
    renderInChat: false,
    enabled: (event) => proposedSources(event.value) !== null,
    render: ({ event, resolve }) => {
      const answer = (choice: SourcesChoice) => void resolve({ decisions: [sourcesDecision(choice)] });
      return preset ? (
        // Keyed by the pause, so a later pause in the same thread is answered too.
        <AutoAnswer key={JSON.stringify(event.value)} preset={preset} onDecide={answer} />
      ) : (
        <>
          <Card access={access} vaultFiles={vaultFiles} onDecide={answer} />
          <PauseSignal onPaused={onPaused} />
        </>
      );
    },
  });
}
