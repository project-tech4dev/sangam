"use client";

import { useCallback, useEffect, useState } from "react";
import { Pencil, Upload } from "lucide-react";
import { Tag } from "@/components/ui";
import { shortDate } from "@/lib/format";
import { type Doc, listVault, uploadToVault } from "../../lib/vault";
import { advance, changedByLine, getProposal, missingFrom, type Proposal, rename, type Saved, saveWork } from "./api";
import { HowItWorks } from "./HowItWorks";
import { ANSWERS, STEPS } from "./steps";
import { TellSangam } from "./TellSangam";

type Save = (set: Record<string, unknown>) => Promise<void>;

/* One proposal: the header, the four steps and the step on screen; every change is saved on the server as it is made. */
export function ProposalShell({ id, onBack }: { id: number; onBack: () => void }) {
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [failed, setFailed] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [missing, setMissing] = useState<string[]>([]);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [selection, setSelection] = useState("");

  const load = useCallback(() => getProposal(id).then(setProposal, () => setFailed(true)), [id]);
  useEffect(() => {
    void load();
  }, [load]);

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
            {work.stage === 2 && <SourcesStep proposal={proposal} save={save} />}
            {work.stage === 3 && <SectionsStep proposal={proposal} />}
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
            <TellSangam proposal={proposal} screen={{ step: STEPS[work.stage - 1], selection }} onTurnEnd={load} />
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

function SourcesStep({ proposal, save }: { proposal: Proposal; save: Save }) {
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

function SectionsStep({ proposal }: { proposal: Proposal }) {
  return (
    <div className="pr-pane">
      <p className="muted">Sangam will write these parts with you, one at a time. Writing is not switched on yet.</p>
      {proposal.tabs.map((tab) => {
        const parts = proposal.sections.filter((s) => s.tab === tab.key);
        if (parts.length === 0) return null;
        return (
          <div key={tab.key} className="card pr-group">
            <div className="card-title">{tab.label}</div>
            <p className="muted">{tab.question}</p>
            {parts.map((s) => (
              <div key={s.code} className="pr-section">
                <strong>{s.label}</strong>
                <span className="muted">{s.question}</span>
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
