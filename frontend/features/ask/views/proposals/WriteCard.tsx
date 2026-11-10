"use client";

import { useEffect, useRef, useState } from "react";
import { Check } from "lucide-react";
import { type Fact, type Part, type Proposal, type Saved, type Section, saveWork, staleFrom } from "./api";
import { source } from "./FactList";

const CITE = /⟦(k\d+)⟧/g;
const PIECE = /((?:⟦k\d+⟧)+|\[Add:[^\]]*\])/;
const SCORE = ["Needs more", "Nearly there", "Strong"];
const RUN = /(?:⟦k\d+⟧)+/g;
const TYPED = /\[(\d+(?:\s*,\s*\d+)*)\]/g;
const SAVE_AFTER_MS = 1500;

/** The person's numbering: sources the text cites by first use, then this part's other facts, so any can be cited. */
export function numbering(text: string, facts: Record<string, Fact>, code: string): string[] {
  const cited = [...text.matchAll(CITE)].map((m) => m[1]).filter((k) => facts[k]);
  const more = Object.entries(facts)
    .filter(([k, f]) => f.section === code && (f.status === "proposed" || f.status === "confirmed") && !cited.includes(k))
    .map(([k]) => k)
    .sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)));
  return [...new Set([...cited, ...more])];
}

/** "⟦k4⟧⟦k7⟧" as "[1,2]" for the text box. */
function numbered(text: string, order: string[]): string {
  return text.replace(RUN, (run) => `[${[...run.matchAll(CITE)].map((m) => order.indexOf(m[1]) + 1).join(",")}]`);
}

/** Back from "[1,2]" to the facts those numbers stood for; a number that stands for none stays as typed. */
function marked(text: string, order: string[]): string {
  return text.replace(TYPED, (typed, list: string) => {
    const keys = list.split(",").map((n) => order[Number(n.trim()) - 1]);
    return keys.every(Boolean) ? keys.map((k) => `⟦${k}⟧`).join("") : typed;
  });
}

/** A section's draft as the funder would read it: each source a numbered mark, each gap in amber, no codes. */
export function WriteCard({ proposal, code }: { proposal: Proposal; code: string }) {
  const saved = proposal.work.sections[code] ?? {};
  const text = saved.text?.trim();
  if (!text) return null;
  const facts = proposal.work.facts ?? {};
  // Numbered by first use in this part, so the marks read 1, 2, 3 down the page.
  const order = [...new Set([...text.matchAll(CITE)].map((m) => m[1]))].filter((k) => facts[k]);
  const gaps = text.match(/\[Add:/g)?.length ?? 0;

  return (
    <div className="pr-draft">
      <div className="pr-draft-state">
        {saved.score != null && <span data-score={saved.score}>{SCORE[saved.score]}</span>}
        {saved.needs_rewrite && <span className="pr-draft-gaps">A fact it uses changed: needs rewriting</span>}
        {gaps > 0 && <span className="pr-draft-gaps">{gaps === 1 ? "1 gap to fill" : `${gaps} gaps to fill`}</span>}
      </div>
      {text.split(/\n\s*\n/).map((para, i) => (
        <p key={i} className="pr-draft-text">
          {para.split(PIECE).map((piece, j) => {
            if (piece.startsWith("⟦")) {
              // Sources side by side read as one mark: "1,2", not "12".
              const keys = [...piece.matchAll(CITE)].map((m) => m[1]).filter((k) => facts[k]);
              return keys.length === 0 ? null : (
                <sup key={j} className="pr-cite" title={keys.map((k) => label(facts[k])).join("\n")}>
                  {keys.map((k) => order.indexOf(k) + 1).join(",")}
                </sup>
              );
            }
            if (piece.startsWith("[Add:")) return <span key={j} className="pr-gap">{piece.slice(1, -1)}</span>;
            return piece;
          })}
        </p>
      ))}
      {order.length > 0 && (
        <ol className="pr-sources" aria-label="Sources">
          {order.map((k) => (
            <li key={k}>{label(facts[k])}</li>
          ))}
        </ol>
      )}
    </div>
  );
}

function label(f: Fact): string {
  const from = source(f) ?? (f.origin === "you_said" ? `${f.said_by?.name ?? "Your team"} said this` : null);
  return `${f.subject}: ${f.value}${from ? ` · ${from}` : ""}`;
}

type Draft = { text: string; order: string[]; rev: number };

function fromServer(part: Part, facts: Record<string, Fact>, code: string): Draft {
  const order = numbering(part.text ?? "", facts, code);
  return { text: numbered(part.text ?? "", order), order, rev: part.rev ?? 0 };
}

/** An open part for an editor: the text with numbered sources, saved as they type, and what code found in it. */
export function PartEditor({
  proposal,
  section,
  next,
  onNext,
  onSaved,
  send,
}: {
  proposal: Proposal;
  section: Section;
  next: Section | null;
  onNext: () => void;
  onSaved: (saved: Saved) => void;
  send: ((text: string) => void) | null;
}) {
  const { code } = section;
  const part = proposal.work.sections[code] ?? {};
  const facts = proposal.work.facts ?? {};
  const [draft, setDraft] = useState(() => fromServer(part, facts, code));
  const [state, setState] = useState<"saved" | "saving" | "checking" | "failed">("saved");
  const [theirs, setTheirs] = useState<{ who: string; mine: string } | null>(null);
  // The latest draft, what the server holds, and the save in flight, read from timers and finished saves.
  const live = useRef({ draft, held: draft.text, flying: false, queued: false, queuedDone: undefined as boolean | undefined });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const me = proposal.thread_id.split("-").slice(2).join("-"); // proposal-<id>-<user id>

  function edit(next: Draft) {
    live.current.draft = next;
    setDraft(next);
  }

  // Someone else saved (Sangam Pitch, a teammate): take their text unless the person has typed since.
  useEffect(() => {
    const { draft: mine, held, flying } = live.current;
    if ((part.rev ?? 0) === mine.rev || flying || mine.text !== held) return;
    const fresh = fromServer(part, facts, code);
    live.current.held = fresh.text;
    edit(fresh);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- follows the part's rev only
  }, [part.rev]);

  async function flush(done?: boolean) {
    if (timer.current) clearTimeout(timer.current);
    const now = live.current;
    if (now.flying) {
      now.queued = true;
      now.queuedDone = done ?? now.queuedDone;
      return;
    }
    const sent = now.draft;
    const set: Record<string, unknown> = {};
    if (sent.text !== now.held) set[`sections.${code}.text`] = marked(sent.text, sent.order);
    if (done !== undefined) set[`sections.${code}.done`] = done;
    if (Object.keys(set).length === 0) return;
    now.flying = true;
    setState(done ? "checking" : "saving");
    try {
      const saved = await saveWork(proposal.id, set, { [code]: sent.rev });
      const after = saved.work.sections[code] ?? {};
      // Renumber only when nothing was typed meanwhile, so the caret never jumps.
      const fresh = now.draft.text === sent.text ? fromServer(after, saved.work.facts ?? {}, code) : null;
      now.held = fresh ? fresh.text : sent.text;
      edit(fresh ?? { ...now.draft, rev: after.rev ?? 0 });
      setState("saved");
      onSaved(saved);
    } catch (error) {
      const stale = staleFrom(error);
      if (!stale) {
        setState("failed");
        return;
      }
      const by = stale.changed_by?.by;
      const fresh = fromServer(stale.current, facts, code);
      setTheirs({ who: !by ? "Someone" : by.id === me ? "Sangam Pitch" : by.name, mine: now.draft.text });
      now.held = fresh.text;
      edit(fresh);
      setState("saved");
    } finally {
      now.flying = false;
      if (now.queued) {
        const queuedDone = now.queuedDone;
        now.queued = false;
        now.queuedDone = undefined;
        void flush(queuedDone);
      }
    }
  }

  function type(text: string) {
    edit({ ...live.current.draft, text });
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void flush(), SAVE_AFTER_MS);
  }

  const missing = part.missing ?? null;
  const untraced = part.untraced ?? [];
  const graded = part.score != null && missing !== null;
  const gaps = draft.text.match(/\[Add:/g)?.length ?? 0;
  const order = draft.order;
  return (
    <>
      <div>
        {section.must_score_2 && <span className="eyebrow">Must score 2</span>}
        <div className="card-title">{section.label}</div>
        <p className="muted pr-part-question">
          {section.question}
          {section.last && <span> Write this last: Sangam Pitch builds it from your finished parts.</span>}
        </p>
      </div>
      {theirs && (
        <div className="pr-edit-theirs" role="status">
          <span>{theirs.who} changed this part a moment ago. Their text is in the box; yours is below to copy from.</span>
          <textarea className="input" readOnly value={theirs.mine} rows={4} aria-label="Your text" />
          <button className="btn btn-ghost" type="button" onClick={() => setTheirs(null)}>
            Done with it
          </button>
        </div>
      )}
      <div className="pr-edit">
        <textarea
          className="input pr-edit-box"
          value={draft.text}
          onChange={(e) => type(e.target.value)}
          onBlur={() => void flush()}
          rows={Math.max(7, draft.text.split("\n").length + 2)}
          aria-label={section.label}
          placeholder="Nothing written yet. Write this part in your own words, or press Write and Sangam Pitch drafts it. Cite a source by its number, like [1]."
        />
        {section.strong.length > 0 && (
          <ul className="pr-covers" aria-label="What a strong answer covers">
            {section.strong.map((e) => {
              const covered = graded && !missing!.includes(e);
              return (
                <li key={e} data-covered={covered}>
                  {covered && "✓ "}
                  {e}
                </li>
              );
            })}
          </ul>
        )}
      </div>
      {untraced.length > 0 && (
        <p className="pr-edit-untraced">
          No source yet: {untraced.map((u) => `“${u}”`).join(", ")}. Cite a fact by its number, change it, or make it a gap
          like [Add: what is missing].
        </p>
      )}
      {order.length > 0 && (
        <div className="pr-edit-sources">
          <h4 className="eyebrow">Sources</h4>
          <ol className="pr-sources" aria-label="Sources">
            {order.map((k) => (
              <li key={k}>{label(facts[k])}</li>
            ))}
          </ol>
        </div>
      )}
      <div className="pr-edit-actions">
        {gaps > 0 && <span className="tag tag-accent">{gaps} to add</span>}
        {graded ? (
          <span className="pr-edit-score">
            <span className="pr-dot" data-score={part.score}>{part.score}</span>
            {part.score === 2 ? "Strong" : part.score === 1 ? "One element missing" : `Reads as weak: ${section.weak}`}
            {section.must_score_2 && part.score! < 2 && " · must be 2"}
          </span>
        ) : (
          draft.text.trim() && section.strong.length > 0 && <span className="muted fm-meta">Press Done to check it against these.</span>
        )}
        <span className="muted fm-meta">{{ saved: "", saving: "Saving…", checking: "Checking…", failed: "Not saved. Keep typing to try again." }[state]}</span>
        <span className="pr-edit-spacer" />
        {!draft.text.trim() ? (
          <button className="btn" type="button" disabled={!send} onClick={() => send?.(`Write ${section.label}.`)}>
            Write
          </button>
        ) : part.done ? (
          <button className="btn btn-ghost" type="button" disabled={state === "checking"} onClick={() => void flush(false)}>
            Done · reopen
          </button>
        ) : (
          <button className="btn btn-primary" type="button" disabled={state === "checking"} onClick={() => void flush(true)}>
            <Check className="icon icon-sm" />
            {state === "checking" ? "Checking…" : "Done"}
          </button>
        )}
        {next && (
          <button className="btn btn-ghost" type="button" onClick={onNext}>
            {next.label} →
          </button>
        )}
      </div>
    </>
  );
}
