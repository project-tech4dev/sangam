"use client";

import { useCallback, useEffect, useState } from "react";
import { Pencil, Upload } from "lucide-react";
import { Tag } from "@/components/ui";
import { shortDate } from "@/lib/format";
import { type Doc, listVault, uploadToVault } from "../../lib/vault";
import { advance, changedByLine, getProposal, missingFrom, type Proposal, type Reader, rename, type Saved, saveWork } from "./api";
import { FactList } from "./FactList";
import { WriteCard } from "./WriteCard";
import { HowItWorks } from "./HowItWorks";
import { ANSWERS, STEPS } from "./steps";
import { TellSangam } from "./TellSangam";

type Save = (set: Record<string, unknown>) => Promise<void>;
type Send = ((text: string) => void) | null;

// Fixed messages the step's buttons send to Sangam Pitch, which calls read_files on either.
const WRITE_FIRST_DRAFT = "Write the first draft.";
const READ_AGAIN = "Read the files again.";
const POLL_MS = 5000;

/* One proposal: the header, the four steps and the step on screen; every change is saved on the server as it is made. */
export function ProposalShell({ id, onBack }: { id: number; onBack: () => void }) {
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [failed, setFailed] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [missing, setMissing] = useState<string[]>([]);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [selection, setSelection] = useState("");
  const [part, setPart] = useState<string | null>(null);
  const [send, setSend] = useState<Send>(null);
  const onSend = useCallback((fn: Send) => setSend(() => fn), []);

  const load = useCallback(() => getProposal(id).then(setProposal, () => setFailed(true)), [id]);
  useEffect(() => {
    void load();
  }, [load]);

  // Files are read in someone's chat turn; every teammate's screen follows the progress from the proposal itself.
  // The presser's own turn counts too: readers are claimed, and parts saved, mid-turn.
  const reading =
    Object.values(proposal?.work.readers ?? {}).some((r) => r.status === "running") ||
    ((proposal?.work.stage === 2 || proposal?.work.stage === 3) && proposal.can_edit && send === null);
  useEffect(() => {
    if (!reading) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [reading, load]);

  async function run(action: () => Promise<Saved>, patch: Partial<Proposal> = {}) {
    setNotice(null);
    setMissing([]);
    try {
      const saved = await action();
      setProposal((p) => (p ? { ...p, ...patch, work: saved.work, summary: saved.summary } : p));
    } catch (error) {
      const changed = changedByLine(error);
      const stillMissing = missingFrom(error);
      if (changed && !stillMissing) {
        setNotice(changed);
        await load();
      } else if (stillMissing) setMissing(stillMissing);
      else setNotice(error instanceof Error ? error.message : "Not saved. Try again.");
    }
  }

  const back = (
    <button className="btn btn-ghost pr-back" type="button" onClick={onBack}>
      ← All proposals
    </button>
  );
  if (!proposal)
    return (
      <>
        {back}
        <p className="muted">{failed ? "This proposal could not be opened." : "Loading…"}</p>
      </>
    );

  const { work, summary, can_edit: canEdit } = proposal;
  const toContinue = summary.to_continue ?? [];
  const save: Save = (set) => run(() => saveWork(id, set));

  function submitRename(event: React.FormEvent) {
    event.preventDefault();
    const title = renaming?.trim();
    if (!title) return;
    setRenaming(null);
    void run(() => rename(id, title), { title });
  }

  return (
    <>
      {back}
      <div className="pr-head">
        <div className="eyebrow">Proposal · {proposal.org.name}</div>
        {renaming === null ? (
          <div className="pr-title-row">
            <h2 className="view-title">{proposal.title}</h2>
            {canEdit && (
              <button className="btn btn-ghost" type="button" onClick={() => setRenaming(proposal.title)} aria-label="Rename">
                <Pencil className="icon icon-sm" />
              </button>
            )}
          </div>
        ) : (
          <form className="pr-title-row" onSubmit={submitRename}>
            <input className="input" value={renaming} onChange={(e) => setRenaming(e.target.value)} aria-label="Proposal name" autoFocus />
            <button className="btn" type="submit" disabled={!renaming.trim()}>
              Save
            </button>
            <button className="btn btn-ghost" type="button" onClick={() => setRenaming(null)}>
              Cancel
            </button>
          </form>
        )}
        <span className="muted fm-meta">
          To {proposal.funder.name}
          {proposal.fit_score !== null && ` · fit ${proposal.fit_score} / 100`} · started {shortDate(proposal.created_at)}
        </span>
        {!canEdit && <p className="pr-readonly">You can read this proposal. Ask your organisation&apos;s admin to make changes.</p>}
      </div>

      <div className="pr-wrap">
        <div className="pr-main">
          <ol className="pr-steps" aria-label="Steps">
            {STEPS.map((label, i) => (
              <li key={label} className="pr-step" data-current={work.stage === i + 1}>
                <button
                  type="button"
                  disabled={!canEdit || i + 1 >= work.stage}
                  onClick={() => save({ stage: i + 1 })}
                  aria-current={work.stage === i + 1 ? "step" : undefined}
                >
                  <span className="pr-step-num">{i + 1}</span>
                  {label}
                </button>
              </li>
            ))}
          </ol>

          {notice && (
            <p className="pr-notice" role="status">
              {notice}
            </p>
          )}

          {/* What the person selects here is sent with their next question to Sangam. */}
          <div onMouseUp={() => setSelection(window.getSelection()?.toString().trim() ?? "")}>
            {work.stage === 1 && <GatesStep proposal={proposal} save={save} />}
            {work.stage === 2 && <SourcesStep proposal={proposal} save={save} send={send} />}
            {work.stage === 3 && <SectionsStep proposal={proposal} part={part} onPart={setPart} save={save} send={send} />}
            {work.stage === 4 && <FinishStep proposal={proposal} />}
          </div>

          {canEdit && work.stage < STEPS.length && (
            <div className="pr-next">
              <button className="btn" type="button" disabled={toContinue.length > 0} onClick={() => run(() => advance(id))}>
                Continue to {STEPS[work.stage].toLowerCase()} →
              </button>
              {(missing.length > 0 ? missing : toContinue).length > 0 && (
                <span className="muted fm-meta">To continue: {(missing.length > 0 ? missing : toContinue).join("; ")}.</span>
              )}
            </div>
          )}

          <div className="pr-strip">
            <Tag tone={summary.ready ? "accent-2" : "outline"}>{summary.ready ? "Ready" : "In progress"}</Tag>
            <span>
              Answered {summary.gates_answered} of {summary.gates_total}
            </span>
            <span>
              Parts done {summary.done} of {summary.total}
            </span>
          </div>
        </div>

        <aside className="pr-side" aria-label="Sangam">
          {canEdit ? (
            <TellSangam
              proposal={proposal}
              screen={{ step: STEPS[work.stage - 1], selection, ...(work.stage === 3 && part ? { part } : {}) }}
              onTurnEnd={load}
              onSend={onSend}
            />
          ) : (
            <section className="card pr-side-card" aria-label="Sangam Pitch">
              <div className="card-title">Sangam Pitch</div>
              <p className="muted pr-chat-note">
                Each person who can change this proposal has their own private chat with Sangam Pitch. You see what they change, not what
                they asked.
              </p>
            </section>
          )}
          {work.stage === 1 && <HowItWorks proposal={proposal} />}
          {work.stage === 2 && <WhatHappensNext funder={proposal.funder.name} />}
        </aside>
      </div>
    </>
  );
}

function GatesStep({ proposal, save }: { proposal: Proposal; save: Save }) {
  const { work, can_edit: canEdit } = proposal;
  const funder = proposal.funder.name;
  return (
    <div className="pr-pane">
      <p className="muted">{funder} asks for these before it reads a proposal. Answer each one.</p>
      {work.requirements.map((r) => {
        const answer = work.gates[r.key] ?? null;
        return (
          <div key={r.key} className="card pr-block">
            <div className="card-title">{r.label}</div>
            <div>
              <h4 className="eyebrow">What {funder} asks</h4>
              <p>{r.rule}</p>
            </div>
            <div>
              <h4 className="eyebrow">What Sangam has on record</h4>
              <p>{r.on_record}</p>
            </div>
            <div className="seg pr-answers" role="radiogroup" aria-label={`Do you have it? ${r.label}`}>
              {ANSWERS.map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  className="seg-opt"
                  aria-checked={answer === value}
                  data-active={answer === value}
                  disabled={!canEdit}
                  onClick={() => save({ [`gates.${r.key}`]: value })}
                >
                  {label}
                </button>
              ))}
            </div>
            {r.hard && answer === "no" && <p className="pr-stop">{funder} cannot fund without this. Get it before you write.</p>}
          </div>
        );
      })}
    </div>
  );
}

function SourcesStep({ proposal, save, send }: { proposal: Proposal; save: Save; send: Send }) {
  const { work, can_edit: canEdit } = proposal;
  const org = proposal.org.slug;
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [style, setStyle] = useState(work.style);
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    listVault(org).then(setDocs, (error: Error) => setProblem(error.message));
  }, [org]);

  async function upload(file: File | undefined, asForm: boolean) {
    if (!file) return;
    setBusy(file.name);
    setProblem(null);
    try {
      const doc = await uploadToVault(org, file);
      setDocs((d) => [doc, ...(d ?? [])]);
      await save(
        asForm
          ? { template: { document_id: doc.id, url: null, from: "upload", read_at: null }, skipped_template: false }
          : { sources: [...work.sources, doc.id] },
      );
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "Not uploaded.");
    } finally {
      setBusy(null);
    }
  }

  const tick = (docId: number, on: boolean) =>
    save({ sources: on ? [...work.sources, docId] : work.sources.filter((d) => d !== docId) });

  return (
    <div className="pr-pane">
      {problem && (
        <p className="import-error" role="alert">
          {problem}
        </p>
      )}
      <div className="card pr-block">
        <div className="card-title">The funder&apos;s form</div>
        {work.template ? (
          <p>
            {work.template.from === "upload" ? "You uploaded it" : "Sangam already has it"}
            {work.template.read_at && ` · from ${shortDate(work.template.read_at)}`}
            {work.template.url && /^https?:\/\//i.test(work.template.url) && (
              <>
                {" · "}
                <a href={work.template.url} target="_blank" rel="noreferrer">
                  open
                </a>
              </>
            )}
            . The proposal follows its order and limits.
          </p>
        ) : work.skipped_template ? (
          <p>
            Using Sangam&apos;s usual order.{" "}
            {canEdit && (
              <button className="btn btn-ghost" type="button" onClick={() => save({ skipped_template: false })}>
                Undo
              </button>
            )}
          </p>
        ) : (
          <>
            <p className="muted">Sangam has no form for {proposal.funder.name}. Upload theirs, or use Sangam&apos;s usual order.</p>
            {canEdit && (
              <div className="pr-next">
                <label className="btn pr-file">
                  <Upload className="icon icon-sm" />
                  {busy ? `Uploading ${busy}…` : "Upload the funder's form"}
                  <input type="file" disabled={Boolean(busy)} onChange={(e) => upload(e.target.files?.[0], true)} />
                </label>
                <button className="btn btn-ghost" type="button" onClick={() => save({ skipped_template: true })}>
                  Use Sangam&apos;s usual order
                </button>
              </div>
            )}
          </>
        )}
      </div>

      <div className="card pr-block">
        <div className="card-title">Documents Sangam may read</div>
        <p className="muted">Tick the files that help: impact reports, evaluations, annual reports, workplans, budgets.</p>
        {!docs ? (
          <div className="muted">Loading…</div>
        ) : docs.length === 0 ? (
          <div className="muted">No files from {proposal.org.name} yet.</div>
        ) : (
          <div className="pr-docs">
            {docs.map((d) => (
              <label key={d.id} className="pr-tick">
                <input
                  type="checkbox"
                  disabled={!canEdit}
                  checked={work.sources.includes(d.id)}
                  onChange={(e) => tick(d.id, e.target.checked)}
                />
                {d.title ?? "Untitled file"}
                {d.doc_type && <span className="muted fm-meta">{d.doc_type.replaceAll("_", " ")}</span>}
              </label>
            ))}
          </div>
        )}
        {canEdit && (
          <label className="btn btn-ghost pr-file">
            <Upload className="icon icon-sm" />
            {busy ? `Uploading ${busy}…` : "Upload a file"}
            <input type="file" disabled={Boolean(busy)} onChange={(e) => upload(e.target.files?.[0], false)} />
          </label>
        )}
      </div>

      <Reading proposal={proposal} send={send} />

      <div className="card pr-block">
        <div className="card-title">Writing style</div>
        <p className="muted">Every part is written in this voice. Change it if you like.</p>
        <textarea
          className="input pr-style"
          value={style}
          readOnly={!canEdit}
          onChange={(e) => setStyle(e.target.value)}
          onBlur={() => canEdit && style !== work.style && save({ style })}
          aria-label="Writing style"
        />
      </div>
    </div>
  );
}

function SectionsStep({
  proposal,
  part,
  onPart,
  save,
  send,
}: {
  proposal: Proposal;
  part: string | null;
  onPart: (code: string | null) => void;
  save: Save;
  send: Send;
}) {
  const saved = proposal.work.sections;
  return (
    <div className="pr-pane">
      <p className="muted">
        Press Write on a tab and Sangam Pitch drafts its parts from the facts, each figure with its source. Where no fact
        supports a part, it leaves a gap and asks you, one question at a time.
      </p>
      {proposal.tabs.map((tab) => {
        const parts = proposal.sections.filter((s) => s.tab === tab.key);
        if (parts.length === 0) return null;
        const written = parts.filter((s) => saved[s.code]?.text?.trim()).length;
        return (
          <div key={tab.key} className="card pr-group">
            <div className="pr-group-head">
              <div>
                <div className="card-title">{tab.label}</div>
                <p className="muted">{tab.question}</p>
              </div>
              {proposal.can_edit && (
                <button className="btn" type="button" disabled={!send} onClick={() => send?.(`Write ${tab.label}.`)}>
                  {written === 0 ? "Write" : "Write again"}
                </button>
              )}
            </div>
            {parts.map((s) => (
              <div key={s.code} className="pr-section" data-open={part === s.code}>
                <button
                  className="pr-section-head"
                  type="button"
                  aria-expanded={part === s.code}
                  onClick={() => onPart(part === s.code ? null : s.code)}
                >
                  <strong>{s.label}</strong>
                  <span className="muted">{saved[s.code]?.text?.trim() ? "Written" : s.question}</span>
                </button>
                {part === s.code && <WriteCard proposal={proposal} code={s.code} />}
                {part === s.code && <FactList proposal={proposal} part={s.code} save={save} />}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function FinishStep({ proposal }: { proposal: Proposal }) {
  const { fix_first: fix, worth_checking: check } = proposal.summary;
  return (
    <div className="pr-pane">
      <div className="card pr-block">
        <div className="card-title">Fix first</div>
        {fix.length ? <Lines lines={fix} /> : <p>Nothing to fix.</p>}
      </div>
      <div className="card pr-block">
        <div className="card-title">Worth checking</div>
        {check.length ? <Lines lines={check} /> : <p>Nothing else to check.</p>}
      </div>
    </div>
  );
}

const Lines = ({ lines }: { lines: string[] }) => (
  <ul className="pr-bars">
    {lines.map((line) => (
      <li key={line}>{line}</li>
    ))}
  </ul>
);

const READ_STATE: Record<Reader["status"], string> = { done: "✓ Read", running: "Reading…", failed: "! Couldn't read" };

/** "Write the first draft", then each file's reader as it runs: read, reading, or what went wrong and "Try again". */
function Reading({ proposal, send }: { proposal: Proposal; send: Send }) {
  const { work, can_edit: canEdit } = proposal;
  const readers = work.readers ?? {};
  const started = Object.keys(readers).length > 0;
  const unread = work.sources.filter((d) => !readers[String(d)]);
  const running = Object.values(readers).find((r) => r.status === "running");
  // The funder's reader cites public links, so its facts are the web ones.
  const factsFrom = (key: string) =>
    Object.values(work.facts ?? {}).filter((f) => (key === "funder" ? f.origin === "web" : String(f.document_id) === key)).length;
  const rows = Object.entries(readers).filter(([key]) => key === "funder" || work.sources.includes(Number(key)));

  return (
    <div className="card pr-block">
      <div className="card-title">Reading your files</div>
      {!started ? (
        <p className="muted">
          When the files are ticked and the style is set, Sangam Pitch reads each file and what {proposal.funder.name} looks for, all
          at once. Every figure it finds becomes a fact for you to check.
        </p>
      ) : (
        <ul className="pr-reads" aria-label="Files read">
          {rows.map(([key, r]) => (
            <li key={key} className="pr-read" data-status={r.status}>
              <span className="pr-read-title">{key === "funder" ? `What ${proposal.funder.name} looks for` : r.title}</span>
              <span className="pr-read-state">
                {READ_STATE[r.status]}
                {r.status === "done" && ` · ${factsFrom(key)} ${factsFrom(key) === 1 ? "fact" : "facts"}`}
                {r.status === "failed" && r.error && `: ${r.error}`}
              </span>
              {r.status === "failed" && canEdit && (
                <button className="btn btn-ghost" type="button" disabled={!send || Boolean(running)} onClick={() => send?.(READ_AGAIN)}>
                  Try again
                </button>
              )}
            </li>
          ))}
          {unread.length > 0 && <li className="muted pr-facts-empty">{unread.length === 1 ? "1 file" : `${unread.length} files`} ticked since, not read yet.</li>}
        </ul>
      )}
      {running && (
        <p className="muted fm-meta">
          {running.by?.name ?? "A teammate"} started reading the files. This takes a few minutes; you can leave this page.
        </p>
      )}
      {canEdit && !running && (!started || unread.length > 0) && (
        <div className="pr-next">
          <button className="btn btn-primary" type="button" disabled={!send} onClick={() => send?.(started ? READ_AGAIN : WRITE_FIRST_DRAFT)}>
            {started ? "Read the new files" : "Write the first draft"}
          </button>
          {!send && <span className="muted fm-meta">Wait for Sangam Pitch to finish its answer.</span>}
        </div>
      )}
    </div>
  );
}

function WhatHappensNext({ funder }: { funder: string }) {
  return (
    <section className="card pr-side-card" aria-label="What happens next">
      <div className="card-title">What happens when you press Write the first draft</div>
      <ol className="pr-explain">
        <li>Sangam Pitch reads every ticked file at the same time, and what Sangam holds on {funder}.</li>
        <li>Each figure, place and finding becomes a fact, with the file and page it came from.</li>
        <li>In step 3 you check the facts part by part, and it asks you about what no file says.</li>
      </ol>
      <p className="muted pr-chat-note">A file it cannot read, such as a scanned image, is listed with a Try again button. The rest carry on.</p>
    </section>
  );
}
