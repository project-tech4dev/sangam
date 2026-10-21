"use client";

import { useCallback, useEffect, useState } from "react";
import { MessageCircle, Pencil, Upload, X } from "lucide-react";
import { Tag } from "@/components/ui";
import { shortDate } from "@/lib/format";
import { type Doc, listVault, uploadToVault } from "../../lib/vault";
import { advance, changedByLine, type Fact, researchAngles, type ResearchAsk, getProposal, missingFrom, type Part, type Proposal, type Reader, rename, type Saved, saveWork, type Section } from "./api";
import { FactList, source } from "./FactList";
import { FinishCard } from "./FinishCard";
import { PartEditor, WriteCard } from "./WriteCard";
import { ANSWERS, CASE_STEP, PLAN_STEP, STEPS } from "./steps";
import { TellSangam } from "./TellSangam";

type Save = (set: Record<string, unknown>) => Promise<void>;
type Send = ((text: string) => void) | null;

// Fixed messages the step's buttons send to Sangam Pitch, which calls read_files on either.
const WRITE_FIRST_DRAFT = "Write the first draft.";
const READ_AGAIN = "Read the files again.";
const SEARCH_PUBLIC = "Search public sources.";
const DEEPER_NEEDS = ["A2", "A3"]; // Context and Problem; the Summary waits for the plan, so it is read but not needed
const ANGLES = 8; // as many as one deeper run takes
const WRITE_SUMMARY = "Write the Summary.";
const POLL_MS = 5000;

/* One proposal: the header, the five steps and the step on screen; every change is saved on the server as it is made. */
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
  // The chat floats over the page: open from the start on a wide screen, behind its button on a phone.
  const [chatOpen, setChatOpen] = useState(() => typeof window !== "undefined" && window.matchMedia("(min-width: 900px)").matches);

  const load = useCallback(() => getProposal(id).then(setProposal, () => setFailed(true)), [id]);
  useEffect(() => {
    void load();
  }, [load]);

  // Files are read in someone's chat turn; every teammate's screen follows the progress from the proposal itself.
  // The presser's own turn counts too: readers are claimed, and parts saved, mid-turn.
  const reading =
    Object.values(proposal?.work.readers ?? {}).some((r) => r.status === "running") ||
    ((proposal?.work.stage ?? 1) >= 2 && proposal?.can_edit && send === null);
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
  const furthest = summary.furthest ?? work.stage;
  const save: Save = (set) => run(() => saveWork(id, set));
  // A step's button talks to Sangam Pitch, so the chat opens to show the reply.
  const ask: Send = send ? (text) => { setChatOpen(true); send(text); } : null;
  const onSaved = (saved: Saved) => setProposal((p) => (p ? { ...p, work: saved.work, summary: saved.summary } : p));

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

      <div className="pr-wrap" data-chat={canEdit && chatOpen}>
        <div className="pr-main">
          <ol className="pr-steps" aria-label="Steps">
            {STEPS.map((label, i) => (
              <li key={label} className="pr-step" data-current={work.stage === i + 1}>
                <button
                  type="button"
                  disabled={!canEdit || i + 1 === work.stage || i + 1 > furthest}
                  onClick={() => (i + 1 < work.stage ? save({ stage: i + 1 }) : run(() => advance(id, i + 1)))}
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
            {work.stage === 2 && <SourcesStep proposal={proposal} save={save} send={ask} />}
            {(work.stage === CASE_STEP || work.stage === PLAN_STEP) && (
              <SectionsStep key={work.stage} step={work.stage} proposal={proposal} part={part} onPart={setPart} save={save} send={ask} onSaved={onSaved} />
            )}
            {work.stage === STEPS.length && <FinishStep proposal={proposal} save={save} send={ask} onSaved={onSaved} />}
          </div>
          {work.stage === 2 && <WhatHappensNext funder={proposal.funder.name} />}

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

      </div>

      {canEdit && (
        <div className="pr-chat-float">
          {/* Hidden, not removed, so a turn keeps streaming while the panel is closed. */}
          <div className="pr-chat-panel" hidden={!chatOpen}>
            <button className="btn btn-ghost pr-chat-close" type="button" onClick={() => setChatOpen(false)} aria-label="Close chat">
              <X className="icon icon-sm" />
            </button>
            <TellSangam
              proposal={proposal}
              screen={{ step: STEPS[work.stage - 1], selection, ...((work.stage === CASE_STEP || work.stage === PLAN_STEP) && part ? { part } : {}) }}
              onTurnEnd={load}
              onSend={onSend}
              open={chatOpen}
            />
          </div>
          {!chatOpen && (
            <button className="btn btn-primary pr-chat-bubble" type="button" onClick={() => setChatOpen(true)}>
              <MessageCircle className="icon icon-sm" />
              Sangam Pitch
            </button>
          )}
        </div>
      )}
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
                  disabled={!canEdit || (d.has_file === false && !work.sources.includes(d.id))}
                  checked={work.sources.includes(d.id)}
                  onChange={(e) => tick(d.id, e.target.checked)}
                />
                {d.title ?? "Untitled file"}
                {d.has_file === false ? (
                  <span className="muted fm-meta">a link to a web page, so Sangam cannot read it; upload the file instead</span>
                ) : (
                  d.doc_type && <span className="muted fm-meta">{d.doc_type.replaceAll("_", " ")}</span>
                )}
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

const INTRO: Record<number, string> = {
  [CASE_STEP]:
    "Make the case for the work: where it happens and the problem, measured. Secondary research adds public evidence on both. The Summary is written last, once the plan is done.",
  [PLAN_STEP]:
    "Press Write on a tab and Sangam Pitch drafts its parts from the facts, each figure with its source. Where no fact supports a part, it leaves a gap and asks you, one question at a time.",
};

/** Step 3 or 4: that step's tabs and parts, one part open; step 3 adds Secondary research. */
function SectionsStep({
  step,
  proposal,
  part,
  onPart,
  save,
  send,
  onSaved,
}: {
  step: number;
  proposal: Proposal;
  part: string | null;
  onPart: (code: string | null) => void;
  save: Save;
  send: Send;
  onSaved: (saved: Saved) => void;
}) {
  const { work, can_edit: canEdit } = proposal;
  const saved = work.sections;
  const sections = proposal.sections.filter((s) => s.step === step);
  const tabs = proposal.tabs.filter((t) => t.step === step && sections.some((s) => s.tab === t.key));
  // The Summary sums up the plan, so it waits for every other part, whichever step they are on.
  const waiting = proposal.sections.filter((s) => !s.last && !saved[s.code]?.text?.trim()).length;
  const isLocked = (s: Section) => s.last && waiting > 0 && !saved[s.code]?.text?.trim();
  // A tab opens on its first part that can be written now.
  const firstOf = (key?: string) => sections.find((s) => s.tab === key && !isLocked(s)) ?? sections.find((s) => s.tab === key);
  const open = sections.find((s) => s.code === part) ?? firstOf(tabs[0]?.key) ?? null;
  // One part is always open, and Sangam Pitch is told which.
  useEffect(() => {
    if (open && part !== open.code) onPart(open.code);
  }, [part, open, onPart]);
  if (!open) return null;

  const tab = tabs.find((t) => t.key === open.tab)!;
  const parts = sections.filter((s) => s.tab === tab.key);
  const next = sections[sections.indexOf(open) + 1] ?? null;
  const score = (key: string) => sections.filter((s) => s.tab === key).reduce((n, s) => n + (saved[s.code]?.score ?? 0), 0);
  const written = parts.filter((s) => saved[s.code]?.text?.trim()).length;
  const cited = new Set(Object.values(saved).flatMap((s) => [...(s.text ?? "").matchAll(/⟦(k\d+)⟧/g)].map((m) => m[1]))).size;
  const gaps = Object.values(saved).reduce((n, s) => n + ((s.text ?? "").match(/\[Add:/g)?.length ?? 0), 0);
  const facts = Object.values(work.facts ?? {}).filter((f) => f.section === open.code && (f.status === "proposed" || f.status === "confirmed")).length;
  const locked = isLocked(open);
  const title = tab.label.replace(/^The /, "the ");

  return (
    <div className="pr-pane">
      <p className="muted">
        {INTRO[step]}
        {canEdit && " You can also write in any part yourself."}
      </p>
      <div className="pr-tabs" role="tablist" aria-label="Proposal sections">
        {tabs.map((t) => (
          <button
            key={t.key}
            className="pr-tab"
            type="button"
            role="tab"
            aria-selected={t.key === tab.key}
            onClick={() => onPart(firstOf(t.key)!.code)}
          >
            {t.label}
            <span className="pr-tab-score">
              {score(t.key)}/{sections.filter((s) => s.tab === t.key).length * 2}
            </span>
          </button>
        ))}
      </div>
      {canEdit && (
        <div className="pr-tab-actions">
          {open.last && waiting === 0 && !saved[open.code]?.text?.trim() && (
            <button className="btn btn-primary" type="button" disabled={!send} onClick={() => send?.(WRITE_SUMMARY)}>
              Write the Summary
            </button>
          )}
          <button className="btn" type="button" disabled={!send} onClick={() => send?.(`Write ${title}.`)}>
            {written === 0 ? `Write ${title}` : `Write ${title} again`}
          </button>
        </div>
      )}
      <div className="pr-body">
        <nav className="pr-parts" aria-label="Parts">
          {parts.map((s) => (
            <button key={s.code} type="button" data-active={s.code === open.code} onClick={() => onPart(s.code)}>
              <span className="pr-parts-label">{s.label}</span>
              <PartDot part={saved[s.code]} />
            </button>
          ))}
        </nav>
        <div className="card pr-editor">
          {locked ? (
            <SummaryWaits section={open} waiting={waiting} />
          ) : canEdit ? (
            <PartEditor key={open.code} proposal={proposal} section={open} next={next} onNext={() => onPart(next?.code ?? null)} onSaved={onSaved} send={send} />
          ) : (
            <>
              <div>
                <div className="card-title">{open.label}</div>
                <p className="muted pr-part-question">{open.question}</p>
              </div>
              {saved[open.code]?.text?.trim() ? <WriteCard proposal={proposal} code={open.code} /> : <p className="muted">Not written yet.</p>}
            </>
          )}
          <details className="import-disclosure">
            <summary className="btn-ghost">Facts for this part ({facts})</summary>
            <FactList proposal={proposal} part={open.code} save={save} />
          </details>
        </div>
      </div>
      <p className="muted fm-meta">
        Cites {cited === 1 ? "1 source" : `${cited} sources`} · {gaps === 1 ? "1 gap" : `${gaps} gaps`} to add · {proposal.summary.done} of{" "}
        {proposal.summary.total} parts done
      </p>
      {step === CASE_STEP && <SecondaryResearch proposal={proposal} save={save} send={send} />}
    </div>
  );
}

/** The Summary before the plan is written: locked, with how much is still empty. */
function SummaryWaits({ section, waiting }: { section: Section; waiting: number }) {
  return (
    <div>
      <div className="card-title">{section.label}</div>
      <p className="muted pr-part-question">{section.question}</p>
      <p>
        Written after your plan. Sangam Pitch writes it once every other part is written: {waiting} {waiting === 1 ? "part is" : "parts are"} still
        empty.
      </p>
    </div>
  );
}

/** A part's state in the list: a dashed dot unwritten, its score once graded, a tick once Done. */
function PartDot({ part }: { part?: Part }) {
  if (!part?.text?.trim()) return <span className="pr-dot" data-score="none" aria-label="Not written">·</span>;
  if (part.done) return <span className="pr-dot" data-score={part.score ?? "none"} aria-label="Done">✓</span>;
  if (part.score == null) return <span className="pr-dot" data-score="none" aria-label="Written, not checked">·</span>;
  return <span className="pr-dot" data-score={part.score} aria-label={`Scored ${part.score} of 2`}>{part.score}</span>;
}

/** What is left before sending, and every fact the text uses for the person to check; Ready is code's call. */
function FinishStep({ proposal, save, send, onSaved }: { proposal: Proposal; save: Save; send: Send; onSaved: (saved: Saved) => void }) {
  const { summary, work, can_edit: canEdit } = proposal;
  const { fix_first: fix, worth_checking: check } = summary;
  const unchecked = Object.entries(work.facts ?? {}).filter(([, f]) => f.status === "proposed" && f.used_in?.length);
  const rewrite = proposal.sections.filter((s) => work.sections[s.code]?.needs_rewrite).map((s) => s.label);
  return (
    <div className="pr-pane">
      <p className="muted">
        {summary.ready
          ? "Nothing stops this proposal. Look over what is worth checking, then send it."
          : "Check each fact the proposal uses. Everything under Fix first stops it being ready; the rest is worth a look."}
      </p>
      <div className="card pr-block">
        <div className="pr-group-head">
          <div className="card-title">Fix first</div>
          {canEdit && rewrite.length > 0 && (
            <button className="btn" type="button" disabled={!send} onClick={() => send?.(`Rewrite ${rewrite.join(", ")}: a fact it uses changed.`)}>
              Rewrite {rewrite.length === 1 ? "that part" : `those ${rewrite.length} parts`}
            </button>
          )}
        </div>
        {fix.length ? <Lines lines={fix} /> : <p>Nothing to fix.</p>}
      </div>
      <div className="card pr-block">
        <div className="card-title">Worth checking</div>
        {check.length ? <Lines lines={check} /> : <p>Nothing else to check.</p>}
      </div>
      <div className="card pr-block">
        <div className="pr-group-head">
          <div>
            <div className="card-title">The facts in your proposal</div>
            <p className="muted">Only facts you confirm go into the final text. Change one and every part that states it follows.</p>
          </div>
          {canEdit && unchecked.length > 1 && (
            <button
              className="btn"
              type="button"
              onClick={() => save(Object.fromEntries(unchecked.map(([k]) => [`facts.${k}.status`, "confirmed"])))}
            >
              Confirm all {unchecked.length}
            </button>
          )}
        </div>
        <FactList proposal={proposal} part="used" save={save} />
      </div>
      <FinishCard proposal={proposal} onSaved={onSaved} />
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
  const started = Object.keys(readers).some((key) => key !== "public");
  const unread = work.sources.filter((d) => !readers[String(d)]);
  const running = Object.entries(readers).find(([key, r]) => key !== "public" && r.status === "running")?.[1];
  // The funder's reader cites web links too; public research's facts carry found_by.
  const from = (f: Fact, key: string) => (key === "funder" ? f.origin === "web" && !f.found_by : String(f.document_id) === key);
  const factsFrom = (key: string) => Object.values(work.facts ?? {}).filter((f) => from(f, key)).length;
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

/** Research deeper from the case: the angles a model reads from it, edited by the person before any search. */
function DeeperResearch({ proposal, send }: { proposal: Proposal; send: Send }) {
  const [angles, setAngles] = useState<string[] | null>(null);
  const [dropped, setDropped] = useState<string[]>([]);
  const [adding, setAdding] = useState("");
  const [state, setState] = useState<"idle" | "reading" | "failed">("idle");
  const held = proposal.work.sections ?? {};
  const waiting = proposal.sections.filter((s) => DEEPER_NEEDS.includes(s.code) && !held[s.code]?.done);

  if (waiting.length > 0) {
    return <p className="muted fm-meta">To research deeper from your case, mark {waiting.map((s) => s.label).join(" and ")} done.</p>;
  }

  async function read() {
    setState("reading");
    try {
      const found = await researchAngles(proposal.id);
      setAngles(found.angles);
      setDropped(found.dropped);
      setState("idle");
    } catch {
      setState("failed");
    }
  }

  function add() {
    const angle = adding.trim();
    if (angle && angles && !angles.includes(angle)) setAngles([...angles, angle]);
    setAdding("");
  }

  if (angles === null) {
    return (
      <div className="pr-next">
        <button className="btn" type="button" disabled={!send || state === "reading"} onClick={() => void read()}>
          {state === "reading" ? "Reading your case…" : "Research deeper from your case"}
        </button>
        {state === "failed" && <span className="muted fm-meta">Sangam couldn&apos;t read your case just now. Try again.</span>}
      </div>
    );
  }
  return (
    <div className="pr-deeper">
      <p className="muted">Sangam Pitch will look into these. Remove any you don&apos;t want or add your own: only these words are searched, never your text.</p>
      <ul className="pr-chips" aria-label="What to look into">
        {angles.map((a) => (
          <li key={a}>
            {a}
            <button type="button" aria-label={`Remove ${a}`} onClick={() => setAngles(angles.filter((x) => x !== a))}>
              <X className="icon icon-sm" />
            </button>
          </li>
        ))}
      </ul>
      {dropped.length > 0 && <p className="muted fm-meta">Left out, since they name your organisation or a person: {dropped.join("; ")}.</p>}
      <form
        className="pr-deeper-add"
        onSubmit={(e) => {
          e.preventDefault();
          add();
        }}
      >
        <input className="input" value={adding} onChange={(e) => setAdding(e.target.value)} aria-label="Add something to look into" placeholder="For example: MGNREGA days worked, Udalguri" />
        <button className="btn btn-ghost" type="submit" disabled={!adding.trim() || angles.length >= ANGLES}>
          Add
        </button>
      </form>
      <div className="pr-next">
        <button
          className="btn btn-primary"
          type="button"
          disabled={!send || angles.length === 0}
          onClick={() => {
            send?.(`Research deeper: ${angles.join("; ")}.`);
            setAngles(null);
          }}
        >
          Search these
        </button>
        <button className="btn btn-ghost" type="button" onClick={() => setAngles(null)}>
          Cancel
        </button>
      </div>
    </div>
  );
}

/** What the person asked secondary research for, newest first, and what each run added. */
function ResearchAsks({ asks }: { asks?: Record<string, ResearchAsk> }) {
  const listed = Object.values(asks ?? {})
    .filter((a) => a.kind !== "plan")
    .sort((a, b) => b.at.localeCompare(a.at));
  if (listed.length === 0) return null;
  return (
    <ul className="pr-asks" aria-label="What you asked for">
      {listed.map((a) => (
        <li key={a.at}>
          <span>{a.ask || a.focus.join("; ") || "More research"}</span>
          <span className="muted fm-meta">
            {[
              a.sites.join(", "),
              a.status === "running" ? "searching…" : a.status === "failed" ? "did not finish" : `${a.added ?? 0} added`,
              shortDate(a.at),
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </li>
      ))}
    </ul>
  );
}

type Topic = NonNullable<Fact["topic"]>;

const TOPICS: [Topic, string][] = [
  ["problem", "The problem, measured"],
  ["place", "Why this place"],
  ["government", "What government does"],
  ["sdg", "SDGs"],
  ["elsewhere", "What worked elsewhere"],
];
const BY_SECTION: Record<string, Topic> = { A3: "problem", A2: "place", A4: "elsewhere", A14: "government" };

// A fact saved before facts carried a topic falls back to its section.
function topicOf(f: Fact): Topic {
  if (f.topic) return f.topic;
  if (f.section === "F1") return f.subject.trim().toUpperCase().startsWith("SDG") ? "sdg" : "government";
  return BY_SECTION[f.section ?? ""] ?? "problem";
}

const CITE = /⟦(k\d+)⟧/g;
const isLive = (f: Fact) => f.status === "proposed" || f.status === "confirmed";

/** Secondary research: its own button, its status, and per topic one summary with numbered sources, used or dropped whole. */
function SecondaryResearch({ proposal, save, send }: { proposal: Proposal; save: Save; send: Send }) {
  const { work, can_edit: canEdit } = proposal;
  const run = work.readers?.public;
  const found = Object.entries(work.facts ?? {}).filter(([, f]) => f.found_by === "public");
  const sources = found.filter(([, f]) => isLive(f)).length;

  return (
    <div className="card pr-block">
      <div className="card-title">Secondary research</div>
      <p className="muted">
        Sangam Pitch searches government and research sources for the problem in the places you work, the schemes on it, the SDGs it serves and
        what worked elsewhere. It never searches for your organisation and never uses your files. Use or drop each topic&apos;s summary.
      </p>
      {run?.status === "running" && (
        <p className="muted fm-meta">{run.by?.name ?? "A teammate"} started the search. This takes a few minutes; you can leave this page.</p>
      )}
      {run?.status === "failed" && <p className="muted fm-meta">! The search did not finish{run.error ? `: ${run.error}` : ""}.</p>}
      {run?.status === "done" && (
        <p className="muted fm-meta">
          Searched {shortDate(run.at)} · {sources} {sources === 1 ? "source" : "sources"}
        </p>
      )}
      <ResearchAsks asks={work.research_asks} />
      {run && run.status !== "running" && (
        <>
          {TOPICS.map(([t, label]) => (
            <ResearchTopic
              key={t}
              label={label}
              summary={run.summaries?.[t]}
              facts={found.filter(([, f]) => topicOf(f) === t)}
              canEdit={canEdit}
              save={save}
            />
          ))}
          {(run.unopened?.length ?? 0) > 0 && <p className="muted fm-meta">Couldn&apos;t open: {run.unopened?.join(", ")}</p>}
        </>
      )}
      {canEdit && run?.status !== "running" && (
        <div className="pr-next">
          <button className={run ? "btn btn-ghost" : "btn btn-primary"} type="button" disabled={!send} onClick={() => send?.(SEARCH_PUBLIC)}>
            {run ? "Search again" : "Search public sources"}
          </button>
          {!send && <span className="muted fm-meta">Wait for Sangam Pitch to finish its answer.</span>}
        </div>
      )}
      {canEdit && run?.status !== "running" && <DeeperResearch proposal={proposal} send={send} />}
      {canEdit && run?.status === "done" && (
        <p className="muted fm-meta">Want more? Tell Sangam Pitch what to dig into or where to look, such as “look at nrlm.gov.in for SHG credit linkage”.</p>
      )}
    </div>
  );
}

/** One topic: its summary with [1]…[n] in place of fact ids, the numbered sources below, and one Use or Don't use. */
function ResearchTopic({
  label,
  summary,
  facts,
  canEdit,
  save,
}: {
  label: string;
  summary?: string;
  facts: [string, Fact][];
  canEdit: boolean;
  save: Save;
}) {
  const live = facts.filter(([, f]) => isLive(f));
  const dropped = facts.filter(([, f]) => f.status === "rejected");
  if (live.length === 0)
    return (
      <details className="fm-weak">
        <summary>
          {label} · {dropped.length > 0 ? "not used" : "none found"}
        </summary>
        {canEdit && dropped.length > 0 && (
          <div className="pr-fact-actions">
            <button className="btn btn-ghost" type="button" onClick={() => save(Object.fromEntries(dropped.map(([k]) => [`facts.${k}.status`, "proposed"])))}>
              Use it after all
            </button>
          </div>
        )}
      </details>
    );

  const ids = new Set(live.map(([k]) => k));
  // Numbered by first citation in the summary; facts it does not cite follow.
  const cited = [...new Set([...(summary ?? "").matchAll(CITE)].map((m) => m[1]))].filter((k) => ids.has(k));
  const order = [...cited, ...live.map(([k]) => k).filter((k) => !cited.includes(k))];
  const n = new Map(order.map((k, i) => [k, i + 1]));
  const byKey = Object.fromEntries(live);
  const text = summary?.replace(/\s*⟦(k\d+)⟧/g, (_, k: string) => (n.has(k) ? ` [${n.get(k)}]` : "")).trim();
  const using = live.every(([, f]) => f.status === "confirmed");
  const setAll = (status: Fact["status"]) => save(Object.fromEntries(live.map(([k]) => [`facts.${k}.status`, status])));

  return (
    <details className="fm-weak" open>
      <summary>
        {label} · {order.length} {order.length === 1 ? "source" : "sources"}
        {using && " · ✓ using it"}
      </summary>
      <div className="pr-research">
        {text ? <p className="pr-research-text">{text}</p> : <p className="muted">No summary for this topic yet. Search again to write one.</p>}
        <ol className="pr-sources" aria-label={`Sources for ${label}`}>
          {order.map((k) => {
            const f = byKey[k];
            const name = source(f) ?? "A public source";
            return (
              <li key={k}>
                {f.source_url && /^https?:\/\//i.test(f.source_url) ? (
                  <a href={f.source_url} target="_blank" rel="noreferrer">
                    {name}
                  </a>
                ) : (
                  name
                )}
                {` · ${f.subject}: ${f.value}${f.as_of ? ` (${f.as_of})` : ""}`}
              </li>
            );
          })}
        </ol>
        {canEdit && (
          <div className="pr-fact-actions">
            {!using && (
              <button className="btn btn-ghost" type="button" onClick={() => setAll("confirmed")}>
                Use this
              </button>
            )}
            <button className="btn btn-ghost" type="button" onClick={() => setAll("rejected")}>
              Don&apos;t use
            </button>
          </div>
        )}
      </div>
    </details>
  );
}

function WhatHappensNext({ funder }: { funder: string }) {
  return (
    <section className="card pr-side-card" aria-label="What happens next">
      <div className="card-title">What happens when you press Write the first draft</div>
      <ol className="pr-explain">
        <li>Sangam Pitch reads every ticked file at the same time, and what Sangam holds on {funder}.</li>
        <li>Each figure, place and finding becomes a fact, with the file and page it came from.</li>
        <li>In steps 3 and 4 you make the case and the plan part by part, and it asks you about what no file says.</li>
      </ol>
      <p className="muted pr-chat-note">A file it cannot read, such as a scanned image, is listed with a Try again button. The rest carry on.</p>
    </section>
  );
}
