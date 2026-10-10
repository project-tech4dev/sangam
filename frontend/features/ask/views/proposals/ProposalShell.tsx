"use client";

import { useEffect, useState } from "react";
import { Pencil, Upload } from "lucide-react";
import { Tag } from "@/components/ui";
import { shortDate } from "@/lib/format";
import { type Doc, listVault, uploadToVault } from "../../lib/vault";
import { displayCodes, GATES, GROUPS, sectionsFor, STEPS } from "./rubric";
import { type Proposal, summary as summarise, updateProposal, useProposals, type Work } from "./store";

/* One proposal: the header, the stepper, and steps 1–2; every change is kept as it is made. */
export function ProposalShell({ id, onBack }: { id: string; onBack: () => void }) {
  const proposal = useProposals().find((p) => p.id === id);
  const [renaming, setRenaming] = useState<string | null>(null);

  if (!proposal)
    return (
      <>
        <button className="btn btn-ghost pr-back" type="button" onClick={onBack}>
          ← All proposals
        </button>
        <p className="muted">This proposal is not in this browser.</p>
      </>
    );
  const { work } = proposal;
  const summary = summarise(work);
  const gatesTicked = summary.gatesMet === summary.gates;
  const templateSettled = Boolean(work.template) || work.skipped_template;
  const reachable = [true, gatesTicked, gatesTicked && templateSettled];
  const save: Save = (change) => updateProposal(id, { work: change });

  function rename(event: React.FormEvent) {
    event.preventDefault();
    if (!renaming?.trim()) return;
    updateProposal(id, { title: renaming.trim() });
    setRenaming(null);
  }

  return (
    <>
      <button className="btn btn-ghost pr-back" type="button" onClick={onBack}>
        ← All proposals
      </button>
      <div className="pr-head">
        <div className="eyebrow">Proposal · {proposal.org.name}</div>
        {renaming === null ? (
          <div className="pr-title-row">
            <h2 className="view-title">{proposal.title}</h2>
            <button className="btn btn-ghost" type="button" onClick={() => setRenaming(proposal.title)} aria-label="Rename">
              <Pencil className="icon icon-sm" />
            </button>
          </div>
        ) : (
          <form className="pr-title-row" onSubmit={rename}>
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
          {proposal.fit_score !== null && ` · fit ${proposal.fit_score} / 100`} · started {shortDate(proposal.created_at)} · kept
          in this browser
        </span>
      </div>

      <ol className="pr-steps" aria-label="Steps">
        {STEPS.map((label, i) => (
          <li key={label} className="pr-step" data-current={work.step === i + 1}>
            <button type="button" disabled={!reachable[i]} onClick={() => save({ step: i + 1 })}>
              <span className="pr-step-num">{i + 1}</span>
              {label}
            </button>
          </li>
        ))}
      </ol>

      {work.step === 1 && <GatesStep proposal={proposal} save={save} ready={gatesTicked} />}
      {work.step === 2 && <SourcesStep proposal={proposal} save={save} ready={templateSettled} />}
      {work.step === 3 && <SectionsStep work={work} />}

      <div className="pr-strip">
        <Tag tone={summary.ready ? "accent-2" : "outline"}>{summary.ready ? "Ready" : "In progress"}</Tag>
        <span>
          Gates {summary.gatesMet} of {summary.gates}
        </span>
        <span>
          Sections done {summary.done} of {summary.total}
        </span>
      </div>
    </>
  );
}

type Save = (change: Partial<Work>) => void;

function GatesStep({ proposal, save, ready }: { proposal: Proposal; save: Save; ready: boolean }) {
  const { work } = proposal;
  return (
    <div className="pr-pane">
      <p className="muted">
        Check both before writing: a proposal that fails either is not read. What Sangam holds is from the latest Funder Match
        run when this proposal started.
      </p>
      {(["G1", "G2"] as const).map((g) => {
        const gate = work.funder_gates[g];
        return (
          <div key={g} className="card pr-block">
            <div className="card-title">
              {g} · {GATES[g]}
            </div>
            <div>
              <h4 className="eyebrow">What {proposal.funder.name} asks</h4>
              <p>{gate.rule}</p>
              {gate.bars.length > 0 && (
                <ul className="pr-bars">
                  {gate.bars.map((bar) => (
                    <li key={bar}>{bar}</li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h4 className="eyebrow">What Sangam holds</h4>
              <p>{gate.on_record}</p>
            </div>
            <label className="pr-tick">
              <input type="checkbox" checked={Boolean(work.gates[g])} onChange={(e) => save({ gates: { ...work.gates, [g]: e.target.checked } })} />
              I&apos;ve checked this against the funder&apos;s own terms
            </label>
          </div>
        );
      })}
      <div className="pr-next">
        <button className="btn" type="button" disabled={!ready} onClick={() => save({ step: 2 })}>
          Continue to template, documents and style →
        </button>
        {!ready && <span className="muted fm-meta">Tick both gates to continue.</span>}
      </div>
    </div>
  );
}

function SourcesStep({ proposal, save, ready }: { proposal: Proposal; save: Save; ready: boolean }) {
  const { work } = proposal;
  const org = proposal.org.slug;
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [style, setStyle] = useState(work.style);
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    listVault(org).then(setDocs, (error: Error) => setProblem(error.message));
  }, [org]);

  async function upload(file: File | undefined, asTemplate: boolean) {
    if (!file) return;
    setBusy(file.name);
    setProblem(null);
    try {
      const doc = await uploadToVault(org, file);
      setDocs((d) => [doc, ...(d ?? [])]);
      save(
        asTemplate
          ? { template: { document_id: doc.id, url: null, from: "upload", read_at: null }, skipped_template: false }
          : { docs: [...work.docs, doc.id] },
      );
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "Not uploaded.");
    } finally {
      setBusy(null);
    }
  }

  const toggle = (docId: number, on: boolean) =>
    save({ docs: on ? [...work.docs, docId] : work.docs.filter((d) => d !== docId) });

  return (
    <div className="pr-pane">
      {problem && <p className="import-error" role="alert">{problem}</p>}
      <div className="card pr-block">
        <div className="card-title">The funder&apos;s template</div>
        {work.template ? (
          <p>
            {work.template.from === "upload" ? "Uploaded to the Doc Vault" : "From Sangam's library"}
            {work.template.read_at && ` · read ${shortDate(work.template.read_at)}`}
            {work.template.url && /^https?:\/\//i.test(work.template.url) && (
              <>
                {" · "}
                <a href={work.template.url} target="_blank" rel="noreferrer">
                  open
                </a>
              </>
            )}
            . Sections follow its order and limits.
          </p>
        ) : work.skipped_template ? (
          <p>
            Skipped: sections follow the rubric&apos;s order.{" "}
            <button className="btn btn-ghost" type="button" onClick={() => save({ skipped_template: false })}>
              Undo
            </button>
          </p>
        ) : (
          <>
            <p className="muted">No template on record for {proposal.funder.name}. Upload theirs, or write to the rubric&apos;s order.</p>
            <div className="pr-next">
              <label className="btn pr-file">
                <Upload className="icon icon-sm" />
                {busy ? `Uploading ${busy}…` : "Upload the funder's template"}
                <input type="file" disabled={Boolean(busy)} onChange={(e) => upload(e.target.files?.[0], true)} />
              </label>
              <button className="btn btn-ghost" type="button" onClick={() => save({ skipped_template: true })}>
                Skip, use the rubric&apos;s order
              </button>
            </div>
          </>
        )}
      </div>

      <div className="card pr-block">
        <div className="card-title">Documents to draw on</div>
        <p className="muted">Ticked Doc Vault files are read when sections are drafted, and cited where they are used.</p>
        {!docs ? (
          <div className="muted">Loading…</div>
        ) : docs.length === 0 ? (
          <div className="muted">Nothing in {proposal.org.name}&apos;s Doc Vault yet.</div>
        ) : (
          <div className="pr-docs">
            {docs.map((d) => (
              <label key={d.id} className="pr-tick">
                <input type="checkbox" checked={work.docs.includes(d.id)} onChange={(e) => toggle(d.id, e.target.checked)} />
                {d.title ?? `Document ${d.id}`}
                {d.doc_type && <span className="muted fm-meta">{d.doc_type.replaceAll("_", " ")}</span>}
              </label>
            ))}
          </div>
        )}
        <label className="btn btn-ghost pr-file">
          <Upload className="icon icon-sm" />
          {busy ? `Uploading ${busy}…` : "Upload a document"}
          <input type="file" disabled={Boolean(busy)} onChange={(e) => upload(e.target.files?.[0], false)} />
        </label>
      </div>

      <div className="card pr-block">
        <div className="card-title">Writing style</div>
        <p className="muted">Every section is drafted and polished in this voice.</p>
        <textarea
          className="input pr-style"
          value={style}
          onChange={(e) => setStyle(e.target.value)}
          onBlur={() => style !== work.style && save({ style })}
          aria-label="Writing style"
        />
      </div>

      <div className="pr-next">
        <button className="btn" type="button" disabled={!ready} onClick={() => save({ step: 3 })}>
          Continue to sections →
        </button>
        {!ready && <span className="muted fm-meta">Add the funder&apos;s template, or skip it, to continue.</span>}
      </div>
    </div>
  );
}

function SectionsStep({ work }: { work: Work }) {
  const sections = sectionsFor(work.earlier_phase);
  const codes = displayCodes(sections);
  return (
    <div className="pr-pane">
      <p className="muted">
        {sections.length} sections, each scored 0–2 against the rubric. Drafting from the record is not switched on yet.
      </p>
      {GROUPS.map(([key, label]) => (
        <div key={key} className="card pr-group">
          <div className="card-title">{label}</div>
          {sections
            .filter((s) => s.group === key)
            .map((s) => (
              <div key={s.code} className="pr-section">
                <span className="pr-section-code">{codes[s.code]}</span>
                <strong>{s.label}</strong>
                <span />
                <span className="muted">{s.question}</span>
              </div>
            ))}
        </div>
      ))}
    </div>
  );
}
