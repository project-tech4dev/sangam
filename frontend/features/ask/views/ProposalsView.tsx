"use client";

import { useState } from "react";
import { ProposalList } from "./proposals/ProposalList";
import { ProposalShell } from "./proposals/ProposalShell";
import { useProposals } from "./proposals/store";

export type ProposalTarget = { id: string } | { funderId: number } | null;

/* The proposals list, or one proposal; the workspace remounts this with a target from Funder Match. */
export function ProposalsView({ target, onFunderMatch }: { target: ProposalTarget; onFunderMatch: () => void }) {
  const [open, setOpen] = useState<string | null>(target && "id" in target ? target.id : null);
  const rows = useProposals();

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
