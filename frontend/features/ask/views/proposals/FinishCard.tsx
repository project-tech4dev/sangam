"use client";

import { useState } from "react";
import { FileText } from "lucide-react";
import { shortDate } from "@/lib/format";
import { differencesFrom, type FormReport, polishProposal, type Proposal, type Saved, saveVersion, versionLink } from "./api";

const headings = (n: number) => (n === 1 ? "1 heading" : `${n} headings`);

/** Step 5's last card: smooth the language under code's check, save a Word file in Sangam's order or the funder's form, open any version. */
export function FinishCard({ proposal, onSaved }: { proposal: Proposal; onSaved: (saved: Saved) => void }) {
  const { work, can_edit: canEdit, summary } = proposal;
  const [busy, setBusy] = useState<"polish" | "save" | "form" | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [differences, setDifferences] = useState<string[]>([]);
  const versions = [...(work.versions ?? [])].reverse();
  const funder = proposal.funder.name;
  const hasForm = Boolean(work.template) && !work.skipped_template;
  const report = versions[0]?.shape === "form" ? versions[0].report : undefined;
  const written = proposal.sections.filter((s) => work.sections[s.code]?.text);
  const polished = work.polished;
  // A part changed after smoothing goes out as written, so the banner names how many.
  const changedSince = polished ? written.filter((s) => polished.revs[s.code] !== (work.sections[s.code]?.rev ?? 0)).length : 0;

  async function act(kind: "polish" | "save" | "form") {
    setBusy(kind);
    setProblem(null);
    setDifferences([]);
    try {
      const saved = await (kind === "polish" ? polishProposal(proposal.id) : saveVersion(proposal.id, kind === "form" ? "form" : "sangam"));
      onSaved(saved);
      const latest = saved.work.versions?.at(-1);
      if (kind !== "polish" && latest) window.location.assign(await versionLink(latest.document_id));
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
          {hasForm && (
            <p className="muted">
              The {funder} form puts the written parts under its own headings. Sangam may shorten a part to fit a limit but never adds
              to it; what it has nothing for is marked [Add], and fields, tables and annexes [You fill].
            </p>
          )}
          <div className="pr-next">
            <button className="btn btn-primary" type="button" disabled={busy !== null} onClick={() => void act("save")}>
              {busy === "save" ? "Saving…" : "Download as a Word file"}
            </button>
            {hasForm && (
              <button className="btn" type="button" disabled={busy !== null} onClick={() => void act("form")}>
                <FileText className="icon icon-sm" />
                {busy === "form" ? `Filling in the ${funder} form… about a minute` : `Download in the ${funder} form`}
              </button>
            )}
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
      {report && <Report report={report} />}
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

/** What went under the form's headings in the newest version, one line each, by the form's own numbers. */
function Report({ report }: { report: FormReport }) {
  const cut = Object.entries(report.cut ?? {});
  return (
    <div className="pr-report" aria-label="What went into the form">
      <p className="pr-report-row">Answered by Sangam: {headings(report.answered.length)}</p>
      {cut.length > 0 && (
        <details className="pr-report-row">
          <summary>Cut to fit: {headings(cut.length)}</summary>
          <ul className="pr-bars">
            {cut.map(([heading, gone]) => (
              <li key={heading}>
                {heading}: {gone.join(", ")}
              </li>
            ))}
          </ul>
        </details>
      )}
      {report.as_written?.length ? <p className="pr-report-row">Put in as written: {report.as_written.join("; ")}</p> : null}
      {report.add.length > 0 && <p className="pr-report-row">Still to add: {report.add.join("; ")}, marked [Add]</p>}
      {report.you_fill.length > 0 && (
        <p className="pr-report-row">Left for you: {headings(report.you_fill.length)}, marked [You fill] in the file</p>
      )}
    </div>
  );
}
