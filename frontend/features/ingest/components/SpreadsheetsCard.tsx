"use client";

import { useEffect, useRef, useState } from "react";
import { useInterrupt } from "@copilotkit/react-core/v2";
import { authHeaders } from "@/lib/api/auth-headers";
import type { TraceStep } from "@/lib/useAgentChat";
import { listedPaths, proposedBucket, proposedPaths } from "../lib/sourcePick";
import type { Workbook } from "../lib/types";
import { PauseSignal } from "./PauseSignal";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

/** One of LangChain's HumanInTheLoopMiddleware decisions; the run resumes with `{decisions: [it]}`. */
export type PickDecision =
  | { type: "approve" }
  | { type: "edit"; edited_action: { name: string; args: Record<string, unknown> } }
  | { type: "reject"; message: string };

const DECLINED: PickDecision = { type: "reject", message: "Staff chose not to use any staff workbook for this run." };

/** A path the agent printed, as a row; it has no size or date. */
function fromPath(path: string): Workbook {
  const parts = path.split("/");
  const folder = parts.slice(1, -1).join("/");
  return { path, name: parts.at(-1) ?? path, folder, folder_label: folder || "Not in a folder", size: null, updated_at: null };
}

function FileList({
  files,
  ticked,
  suggested,
  onToggle,
  disabled,
}: {
  files: Workbook[];
  ticked: Set<string>;
  suggested: Set<string>;
  onToggle: (path: string) => void;
  disabled: boolean;
}) {
  return (
    <ul className="import-files">
      {files.map((f) => (
        <li key={f.path}>
          <label className="import-file">
            <input type="checkbox" checked={ticked.has(f.path)} onChange={() => onToggle(f.path)} disabled={disabled} />
            <span className="import-file-name">
              <strong>{f.name}</strong>
              <span>{[f.folder_label, f.updated_at && `added ${f.updated_at}`].filter(Boolean).join(" · ")}</span>
            </span>
            {suggested.has(f.path) && <span className="tag tag-accent-2">Suggested</span>}
          </label>
        </li>
      ))}
    </ul>
  );
}

/**
 * Both source pauses as one question. At the first (list_bucket_files) staff see the bucket's
 * workbooks and tick some; `onPick` remembers them so the second pause is answered without asking.
 */
function Card({
  bucket,
  prefix,
  offered,
  proposed,
  onDecide,
  onPick,
}: {
  bucket: string | null;
  prefix: string;
  /** Without a bucket, the files to choose from are the ones the agent proposed or listed. */
  offered: Workbook[];
  proposed: string[];
  onDecide: (decision: PickDecision) => void;
  onPick: (paths: string[]) => void;
}) {
  const [files, setFiles] = useState<Workbook[] | null>(bucket ? null : offered);
  const [failed, setFailed] = useState(false);
  const [folder, setFolder] = useState<string | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(() => new Set(proposed));
  const [sent, setSent] = useState(false);

  useEffect(() => {
    if (!bucket) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/ingest/workbooks?bucket=${encodeURIComponent(bucket)}`, {
          headers: await authHeaders(),
        });
        if (!res.ok) throw new Error(String(res.status));
        const found: Workbook[] = await res.json();
        if (cancelled) return;
        const folderOf = prefix.replace(/\/$/, "");
        setFiles(found);
        if (folderOf) setTicked(new Set(found.filter((f) => f.folder.startsWith(folderOf)).map((f) => f.path)));
        setFolder(found.find((f) => folderOf && f.folder.startsWith(folderOf))?.folder ?? found[0]?.folder ?? null);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [bucket, prefix]);

  const folderOf = prefix.replace(/\/$/, "");
  const suggested = new Set(
    bucket ? (files ?? []).filter((f) => folderOf && f.folder.startsWith(folderOf)).map((f) => f.path) : proposed,
  );
  const folders = [...new Map((files ?? []).map((f) => [f.folder, f.folder_label])).entries()];
  const shown = (files ?? []).filter((f) => !bucket || folders.length < 2 || f.folder === folder);
  const count = ticked.size;

  function toggle(path: string) {
    setTicked((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  function decide(decision: PickDecision) {
    setSent(true);
    onDecide(decision);
  }

  function use() {
    const paths = (files ?? []).map((f) => f.path).filter((p) => ticked.has(p));
    if (!bucket) {
      const unchanged = paths.length === proposed.length && proposed.every((p) => ticked.has(p));
      return decide(unchanged ? { type: "approve" } : { type: "edit", edited_action: { name: "select_source_files", args: { paths } } });
    }
    onPick(paths);
    // The listing the agent sees is narrowed to the one folder when every ticked file is in it.
    const only = new Set((files ?? []).filter((f) => ticked.has(f.path)).map((f) => f.folder));
    const narrowed = only.size === 1 ? [...only][0]! : "";
    decide(
      narrowed === folderOf
        ? { type: "approve" }
        : { type: "edit", edited_action: { name: "list_bucket_files", args: { bucket, prefix: narrowed } } },
    );
  }

  return (
    <section className="import-pick" aria-label="Your team's spreadsheets">
      <div className="import-head">
        <span className="card-kicker">Sangam needs your answer</span>
        <strong className="import-pick-title">Should Sangam also look at your team&apos;s spreadsheets?</strong>
        <span className="import-pick-text">
          {bucket
            ? "These are in your team's shared files. Nothing is opened until you choose."
            : "Sangam ticked the ones that look useful. Nothing is opened until you choose."}
        </span>
      </div>

      {files === null && !failed && <span className="muted">Looking in your team&apos;s files…</span>}
      {failed && (
        <span className="import-pick-text">Sangam couldn&apos;t list the files here. It can list them itself and ask you again.</span>
      )}
      {files !== null && files.length === 0 && (
        <span className="import-pick-text">There are no spreadsheets in your team&apos;s files.</span>
      )}

      {bucket && folders.length > 1 && (
        <div className="import-names">
          <span className="import-label">Which folder?</span>
          <div className="seg import-seg">
            {folders.map(([value, label]) => (
              <button key={value} type="button" className="seg-opt" data-active={value === folder} onClick={() => setFolder(value)}>
                {label}
              </button>
            ))}
          </div>
        </div>
      )}
      {shown.length > 0 && <FileList files={shown} ticked={ticked} suggested={suggested} onToggle={toggle} disabled={sent} />}

      <div className="import-pick-actions">
        {failed ? (
          <button type="button" className="btn btn-primary" onClick={() => decide({ type: "approve" })} disabled={sent}>
            Let Sangam list them
          </button>
        ) : (
          files !== null &&
          files.length > 0 && (
            <button type="button" className="btn btn-primary" onClick={use} disabled={sent || count === 0}>
              Use {count === 1 ? "this file" : `these ${count} files`}
            </button>
          )
        )}
        <button type="button" className="btn btn-secondary" onClick={() => decide(DECLINED)} disabled={sent}>
          No, only public websites
        </button>
      </div>
    </section>
  );
}

/** The second pause, when the files were already chosen at the first: answered once, on mount. */
function Answered({ onAnswer }: { onAnswer: () => void }) {
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    onAnswer();
  }, [onAnswer]);
  return <span className="muted">Using the files you chose…</span>;
}

/** Shows the spreadsheets question while the run is paused on either source tool. */
export function SpreadsheetsCard({
  agentId,
  steps,
  onPaused,
}: {
  agentId: string;
  steps: TraceStep[];
  onPaused: (paused: boolean) => void;
}) {
  const picked = useRef<string[] | null>(null);
  return useInterrupt({
    agentId,
    renderInChat: false,
    enabled: (event) => proposedPaths(event.value) !== null || proposedBucket(event.value) !== null,
    render: ({ event, resolve }) => {
      const answer = (decision: PickDecision) => void resolve({ decisions: [decision] });
      const bucket = proposedBucket(event.value);
      const paths = proposedPaths(event.value);
      if (paths !== null && picked.current) {
        const chosen = picked.current;
        return (
          <Answered
            onAnswer={() => {
              picked.current = null;
              answer({ type: "edit", edited_action: { name: "select_source_files", args: { paths: chosen } } });
            }}
          />
        );
      }
      const proposed = paths ?? [];
      return (
        <>
          <Card
            bucket={bucket?.bucket || null}
            prefix={bucket?.prefix ?? ""}
            offered={bucket ? [] : [...new Set([...proposed, ...listedPaths(steps)])].map(fromPath)}
            proposed={proposed}
            onDecide={answer}
            onPick={(chosen) => {
              picked.current = chosen;
            }}
          />
          <PauseSignal onPaused={onPaused} />
        </>
      );
    },
  });
}
