"use client";

import { useSyncExternalStore } from "react";
import { ProposalList } from "./proposals/ProposalList";
import { ProposalShell } from "./proposals/ProposalShell";
import { hadBrowserProposals, useProposals } from "./proposals/api";

const noop = () => () => {};

export type ProposalTarget = { id: number } | { funderId: number } | null;

/* The proposals list, or one proposal; both come from the address, so Back returns to the list. */
export function ProposalsView({ open, funder, onOpen, onFunderMatch }: {
  open: number | null;
  funder: number | null;
  onOpen: (id: number | null) => void;
  onFunderMatch: () => void;
}) {
  const rows = useProposals();
  const oldOnes = useSyncExternalStore(noop, hadBrowserProposals, () => false);

  return (
    <div className="view">
      {open !== null ? (
        <ProposalShell key={open} id={open} onBack={() => onOpen(null)} />
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
            key={funder ?? "all"}
            rows={rows}
            initialFunder={funder}
            onOpen={onOpen}
            onFunderMatch={onFunderMatch}
          />
        </>
      )}
    </div>
  );
}
