"use client";

import { useState } from "react";
import { shortDate } from "@/lib/format";
import { differencesFrom, polishProposal, type Proposal, type Saved, saveVersion, versionLink } from "./api";

/** Step 4's last card: smooth the language under code's check, save it as a Word file in the Doc Vault, open any version. */
export function FinishCard({ proposal, onSaved }: { proposal: Proposal; onSaved: (saved: Saved) => void }) {
  const { work, can_edit: canEdit, summary } = proposal;
  const [busy, setBusy] = useState<"polish" | "save" | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [differences, setDifferences] = useState<string[]>([]);
  const versions = [...(work.versions ?? [])].reverse();
  const written = proposal.sections.filter((s) => work.sections[s.code]?.text);
  const polished = work.polished;
  // A part changed after smoothing goes out as written, so the banner names how many.
  const changedSince = polished ? written.filter((s) => polished.revs[s.code] !== (work.sections[s.code]?.rev ?? 0)).length : 0;

  async function act(kind: "polish" | "save") {
    setBusy(kind);
    setProblem(null);
    setDifferences([]);
    try {
      const saved = await (kind === "polish" ? polishProposal(proposal.id) : saveVersion(proposal.id));
      onSaved(saved);
      const latest = saved.work.versions?.at(-1);
      if (kind === "save" && latest) window.location.assign(await versionLink(latest.document_id));
    } catch (error) {
      const refused = differencesFrom(error);
      if (refused?.length) setDifferences(refused);
      else setProblem(error instanceof Error && typeof error.message === "string" ? error.message : "That didn't work. Try again.");
    } finally {
      setBusy(null);
    }
  }

  async function open(documentId: number) {
    setProblem(null);
    try {
      window.location.assign(await versionLink(documentId));
    } catch {
      setProblem("That file could not be opened. Try again.");
    }
  }

  return (
    <div className="card pr-block">
      <div className="card-title">Your proposal as a Word file</div>
      <p className="muted">
        Sangam never sends anything to {proposal.funder.name}: you download the file, read it through and send it yourself.
        {!summary.ready && " The file marks every gap still to fill."}
      </p>
      {canEdit && written.length > 0 && (
        <>
          <p className="muted">
            {polished
              ? `The language was smoothed on ${shortDate(polished.at)} by ${polished.by.name}.` +
                (changedSince ? ` ${changedSince === 1 ? "1 part has" : `${changedSince} parts have`} changed since and will go out as written; smooth it again to include ${changedSince === 1 ? "it" : "them"}.` : "")
              : "Smoothing the language makes the parts read as one document. Sangam then checks that no figure, place, name or gap changed, and keeps nothing if one did."}
          </p>
          <div className="pr-next">
            <button className="btn btn-primary" type="button" disabled={busy !== null} onClick={() => void act("save")}>
              {busy === "save" ? "Saving…" : "Download as a Word file"}
            </button>
            <button className="btn" type="button" disabled={busy !== null} onClick={() => void act("polish")}>
              {busy === "polish" ? "Smoothing… about a minute" : polished ? "Smooth the language again" : "Smooth the language"}
            </button>
          </div>
        </>
      )}
      {differences.length > 0 && (
        <div role="alert">
          <p className="pr-stop">The smoothed wording changed what the proposal says, so it was not kept:</p>
          <ul className="pr-bars">
            {differences.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </div>
      )}
      {problem && (
        <p className="pr-stop" role="alert">
          {problem}
        </p>
      )}
      {versions.length ? (
        <ul className="pr-reads" aria-label="Saved versions">
          {versions.map((v) => (
            <li key={v.n} className="pr-read" data-status="done">
              <span className="pr-read-title">{v.title}</span>
              <span className="pr-read-state">
                {shortDate(v.at)} · {v.by.name} · in the Doc Vault
              </span>
              <button className="btn btn-ghost" type="button" onClick={() => void open(v.document_id)}>
                Download
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">{written.length ? "No version saved yet. Each download is kept in your Doc Vault as the next version." : "Nothing is written yet."}</p>
      )}
    </div>
  );
}
