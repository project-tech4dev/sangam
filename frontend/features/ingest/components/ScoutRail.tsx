"use client";

import type { ImportAccess, VaultFile } from "../lib/access";
import { isPull, type ImportTask } from "../lib/composePrompt";
import type { SourcesChoice } from "../lib/sourcePick";
import type { ImportRun, ImportSource, QueueItem, SourceProposal } from "../lib/types";
import { SourcePicker } from "./SourcePicker";
import { WaitingForYou } from "./WaitingForYou";

export type StaffPanels = { sources: ImportSource[]; runs: ImportRun[]; queue: QueueItem[]; proposals: SourceProposal[] };

/** Scout's right rail: where it may read from before the first message, what it read from after. */
export function ScoutRail({
  started,
  task,
  sources,
  onSources,
  readFrom,
  access,
  vaultFiles,
  staff,
}: {
  started: boolean;
  task: ImportTask | null;
  sources: SourcesChoice;
  onSources: (next: SourcesChoice) => void;
  readFrom: string | null;
  access: ImportAccess;
  vaultFiles: VaultFile[];
  staff: StaffPanels | null;
}) {
  return (
    <aside className="scout-rail" aria-label="Scout's sources">
      {!started && task !== null && !isPull(task) && (
        <section className="card scout-rail-section">
          <span className="card-kicker">Before Scout starts</span>
          <strong className="card-title">Where should Scout read from?</strong>
          <span className="card-body">Nothing is opened until you choose. Scout reads only what you tick.</span>
          <SourcePicker
            value={sources}
            onChange={onSources}
            staff={access.staff}
            vaultFiles={vaultFiles}
            showOrg={access.orgs.length > 1}
          />
        </section>
      )}
      {!started && task === null && (
        <section className="card scout-rail-section">
          <strong className="card-title">Where Scout reads from</strong>
          <span className="card-body">Pick a task, then choose websites, Sangam&apos;s library or your Doc Vault files here.</span>
        </section>
      )}
      {started && readFrom && (
        <section className="card scout-rail-section">
          <span className="card-kicker">Reading from</span>
          <span className="card-body">{readFrom}</span>
        </section>
      )}
      {staff && <WaitingForYou items={staff.queue} sources={staff.sources} />}
    </aside>
  );
}
