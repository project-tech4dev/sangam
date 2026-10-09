"use client";

import { useState } from "react";
import { tasksFor, type ImportAccess, type VaultFile } from "../lib/access";
import { composePrompt, type ImportTask, type NewsSource, type VaultPick } from "../lib/composePrompt";

const TASKS: { id: ImportTask; title: string; desc: string }[] = [
  { id: "funder", title: "Research a funder", desc: "How to apply, who is eligible, and which documents they want." },
  { id: "ngo", title: "Check an NGO", desc: "Is it ready for CSR money — registrations, accounts and track record." },
  { id: "news", title: "Get the latest CSR news", desc: "Read recent articles and update the funders Sangam already knows." },
];
const NEWS_SOURCES: NewsSource[] = ["India CSR", "GDELT"];
const NEWS_COUNTS = [5, 10, 20];

const plural = (n: number, word: string) => `${n || ""} ${word}${n === 1 ? "" : "s"}`.trim();

/** Step 1: pick a task and the names, and the request is written for you. */
export function StartStep({
  onStart,
  disabled,
  access,
  vaultFiles = [],
}: {
  onStart: (prompt: string) => void;
  disabled: boolean;
  access: ImportAccess;
  vaultFiles?: VaultFile[];
}) {
  const allowed = tasksFor(access);
  const tasks = TASKS.filter((t) => allowed.includes(t.id));
  const [task, setTask] = useState<ImportTask>("funder");
  const [names, setNames] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [source, setSource] = useState<NewsSource>("India CSR");
  const [count, setCount] = useState(5);
  const [picked, setPicked] = useState<VaultPick | null>(null);
  const isNews = task === "news";

  // One organisation's files per request: picking another's starts a new pick.
  function toggleFile(f: VaultFile) {
    const ids = picked?.org === f.org ? picked.ids : [];
    const next = ids.includes(f.id) ? ids.filter((i) => i !== f.id) : [...ids, f.id];
    setPicked(next.length ? { org: f.org, orgName: f.orgName, ids: next } : null);
  }

  const has = (name: string) => names.some((n) => n.toLowerCase() === name.toLowerCase());

  function addName() {
    const name = draft.trim();
    if (name && !has(name)) setNames([...names, name]);
    setDraft("");
  }

  // A name still in the box counts: people type one and press Start.
  const typed = draft.trim();
  const pending = typed && !has(typed) ? [...names, typed] : names;
  const label = isNews ? "Get the news →" : task === "ngo" ? `Check ${plural(pending.length, "NGO")} →` : `Research ${plural(pending.length, "funder")} →`;

  return (
    <section className="import-start">
      <div className="import-head">
        <h1 className="import-h1">What would you like to find out?</h1>
        <p className="import-sub">Sangam reads public websites and filings, and shows you where every answer came from.</p>
      </div>

      <div role="radiogroup" aria-label="Task" className="import-tasks">
        {tasks.map((t) => (
          <button
            key={t.id}
            type="button"
            role="radio"
            aria-checked={task === t.id}
            className="import-task"
            onClick={() => setTask(t.id)}
          >
            <span className="import-task-title">
              <span className="import-task-radio" />
              {t.title}
            </span>
            <span className="import-task-desc">{t.desc}</span>
          </button>
        ))}
      </div>

      {!isNews && (
        <div className="import-names">
          <label htmlFor="import-name" className="import-label">
            {task === "ngo" ? "Which NGOs?" : "Which funders?"}
          </label>
          <div className="import-name-row">
            <input
              id="import-name"
              className="input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addName();
                }
              }}
              placeholder={task === "ngo" ? "Type an NGO's name…" : "Type a funder's name…"}
            />
            <button type="button" className="btn btn-secondary" onClick={addName}>
              Add
            </button>
          </div>
          <span className="import-hint">Press Enter after each name. Add as many as you like.</span>
          {task === "ngo" && !access.staff && (
            <div className="import-chips">
              <span className="import-hint">The NGOs you support:</span>
              {access.stewardOf
                .filter((n) => !has(n))
                .map((n) => (
                  <button key={n} type="button" className="import-chip" onClick={() => setNames([...names, n])}>
                    + {n}
                  </button>
                ))}
            </div>
          )}
          {names.length > 0 && (
            <div className="import-chips">
              {names.map((n) => (
                <span key={n} className="import-chip">
                  {n}
                  <button
                    type="button"
                    aria-label={`Remove ${n}`}
                    className="import-chip-x"
                    onClick={() => setNames(names.filter((x) => x !== n))}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {!isNews && vaultFiles.length > 0 && (
        <div className="import-names">
          <span className="import-label">Read your organisation&apos;s documents first? (optional)</span>
          <div className="import-chips">
            {vaultFiles.map((f) => (
              <button
                key={f.id}
                type="button"
                className="import-chip import-file"
                aria-pressed={picked?.org === f.org && picked.ids.includes(f.id)}
                onClick={() => toggleFile(f)}
              >
                {f.title || `Document ${f.id}`}
                {access.orgs.length > 1 && <span className="import-hint"> · {f.orgName}</span>}
              </button>
            ))}
          </div>
          <span className="import-hint">
            Sangam reads them privately, then searches the web only for what they don&apos;t answer.{" "}
            {task === "ngo"
              ? "What they say is shown for review and never saved to the NGO's record."
              : "Only the funder's general facts are saved from them; your own grants and contacts stay with you."}
          </span>
        </div>
      )}

      {isNews && (
        <div className="import-news">
          <div className="import-news-opt">
            <span className="import-label">Where from?</span>
            <div className="seg">
              {NEWS_SOURCES.map((s) => (
                <button key={s} type="button" className="seg-opt" data-active={source === s} onClick={() => setSource(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
          <div className="import-news-opt">
            <span className="import-label">How many articles?</span>
            <div className="seg">
              {NEWS_COUNTS.map((n) => (
                <button key={n} type="button" className="seg-opt" data-active={count === n} onClick={() => setCount(n)}>
                  {n}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="import-begin">
        <button
          type="button"
          className="btn btn-primary"
          disabled={disabled || (!isNews && pending.length === 0)}
          onClick={() => onStart(composePrompt(task, pending, { source, count }, picked ?? undefined))}
        >
          {label}
        </button>
        <span className="import-sub">Takes a few minutes for each organisation. Nothing is saved until you say so.</span>
      </div>
    </section>
  );
}
