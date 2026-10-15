"use client";

import { useState, useSyncExternalStore } from "react";
import { ProposalList } from "./proposals/ProposalList";
import { ProposalShell } from "./proposals/ProposalShell";
import { hadBrowserProposals, useProposals } from "./proposals/api";

const noop = () => () => {};

export type ProposalTarget = { id: number } | { funderId: number } | null;

/* The proposals list, or one proposal; the workspace remounts this with a target from Funder Match. */
export function ProposalsView({ target, onFunderMatch }: { target: ProposalTarget; onFunderMatch: () => void }) {
  const [open, setOpen] = useState<number | null>(target && "id" in target ? target.id : null);
  const rows = useProposals();
  const oldOnes = useSyncExternalStore(noop, hadBrowserProposals, () => false);

  return (
    <div className="view">
      {open !== null ? (
        <ProposalShell id={open} onBack={() => setOpen(null)} />
      ) : (
        <>
          <div className="pr-head">
            <div className="eyebrow">Use Cases</div>
            <h2 className="view-title">Proposals</h2>
          </div>
          {oldOnes && (
            <p className="pr-notice">
              Proposals started before today were kept in this browser only and are not shown here. Start them again from Funder
              Match; everyone in your organisation will then see them.
            </p>
          )}
          <ProposalList
            rows={rows}
            initialFunder={target && "funderId" in target ? target.funderId : null}
            onOpen={setOpen}
            onFunderMatch={onFunderMatch}
          />
        </>
      )}
    </div>
  );
}
