"use client";

import { ChevronDown, CircleStop, FileText, LoaderCircle, Upload } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { selectClass } from "../members-api";
import { BUCKETS, DEFAULT_GROUP, graphStream, groupBody, type ChunkResult, type DocumentEvent } from "./graph-api";
import { Card, ErrorText, ExtractionResult, Field, GROUP_HINT, inputClass } from "./graph-ui";

type FileState = {
  key: string;
  status: "waiting" | "running" | "added" | "skipped" | "failed" | "stopped";
  step: string;
  totalChunks: number;
  parts: ChunkResult[];
  current: { index: number; chars: number; episode: string; preview: string } | null;
  reason: string | null;
};

type Listed = Extract<DocumentEvent, { event: "listed" }>;
type LogLine = { at: string; text: string };

const kb = (bytes: number | null) => (bytes == null ? "size unknown" : `${(bytes / 1024).toFixed(1)} KB`);

function describe(event: DocumentEvent): string {
  switch (event.event) {
    case "listing":
      return `Listing ${event.bucket}/${event.prefix || ""}…`;
    case "listed":
      return `Found ${event.found} files; reading ${event.reading.length} into group ${event.group_id}`;
    case "file_start":
      return `File ${event.number} of ${event.total}: ${event.key}`;
    case "downloading":
      return `Downloading ${event.key} (${kb(event.bytes)})`;
    case "extracting":
      return `Extracting text from ${event.type ?? "file"} (${kb(event.bytes)})`;
    case "chunked":
      return `${event.chars.toLocaleString()} characters → ${event.chunks} chunks of up to ${event.chunk_chars.toLocaleString()}`;
    case "chunk_start":
      return `Chunk ${event.index}/${event.total} → Graphiti as episode ${event.episode}`;
    case "chunk_done":
      return event.chunk.status === "skipped"
        ? `Chunk ${event.chunk.index}/${event.total} already in the graph, skipped`
        : `Chunk ${event.chunk.index}/${event.total}: ${event.chunk.entities.length} entities, ${event.chunk.facts.length} facts kept, ${event.chunk.dropped_facts.length} dropped`;
    case "file_done":
      return `${event.file.key}: ${event.file.status}${event.file.reason ? ` (${event.file.reason})` : ""}`;
    case "done":
      return "Done";
  }
}

function apply(files: FileState[], event: DocumentEvent): FileState[] {
  const update = (key: string, change: (f: FileState) => Partial<FileState>) =>
    files.map((f) => (f.key === key ? { ...f, ...change(f) } : f));
  switch (event.event) {
    case "listed":
      return event.reading.map((key) => ({
        key,
        status: "waiting",
        step: "Waiting",
        totalChunks: 0,
        parts: [],
        current: null,
        reason: null,
      }));
    case "file_start":
    case "downloading":
      return update(event.key, () => ({ status: "running", step: "Downloading" }));
    case "extracting":
      return update(event.key, () => ({ step: "Extracting text" }));
    case "chunked":
      return update(event.key, () => ({ step: `Split into ${event.chunks} chunks`, totalChunks: event.chunks }));
    case "chunk_start":
      return update(event.key, () => ({
        step: `Extracting entities from chunk ${event.index} of ${event.total}`,
        current: { index: event.index, chars: event.chars, episode: event.episode, preview: event.preview },
      }));
    case "chunk_done":
      return update(event.key, (f) => ({ parts: [...f.parts, event.chunk], current: null }));
    case "file_done":
      return update(event.file.key, () => ({
        status: event.file.status,
        step: "Finished",
        parts: event.file.parts,
        current: null,
        reason: event.file.reason,
      }));
    default:
      return files;
  }
}

function stopAll(files: FileState[]): FileState[] {
  return files.map((f) =>
    f.status === "running" || f.status === "waiting"
      ? {
          ...f,
          status: "stopped",
          current: null,
          reason: f.parts.length
            ? `Stopped after ${f.parts.length} of ${f.totalChunks || "?"} chunks`
            : "Stopped before it started",
        }
      : f,
  );
}

function FileRow({ file }: { file: FileState }) {
  const [open, setOpen] = useState(true);
  const added = file.parts.filter((p) => p.status === "added");
  const entities = added.reduce((n, p) => n + p.entities.length, 0);
  const facts = added.reduce((n, p) => n + p.facts.length, 0);
  const tone =
    file.status === "added"
      ? "text-accent-750"
      : file.status === "failed"
        ? "text-terracotta-750"
        : "text-neutral-500";

  return (
    <li className="rounded-lg border border-neutral-200">
      <button
        type="button"
        className="flex w-full cursor-pointer flex-wrap items-center gap-3 bg-transparent p-3 text-left text-sm"
        onClick={() => setOpen(!open)}
      >
        {file.status === "running" ? (
          <LoaderCircle className="icon icon-sm animate-spin" aria-hidden />
        ) : (
          <FileText className="icon icon-sm" aria-hidden />
        )}
        <span className="min-w-0 flex-1 truncate font-medium">{file.key}</span>
        <span className={tone}>{file.status === "running" ? file.step : file.status}</span>
        <span className="text-neutral-600">
          {file.parts.length}/{file.totalChunks || "?"} chunks · {entities} entities · {facts} facts
        </span>
        <ChevronDown className={`icon icon-sm ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {file.reason && <p className="px-3 pb-3 text-sm text-neutral-600">{file.reason}</p>}
      {open && (file.parts.length > 0 || file.current) && (
        <ol className="flex flex-col gap-3 border-t border-neutral-200 p-3">
          {file.parts.map((part) => (
            <li key={part.index} className="flex flex-col gap-2 rounded-lg bg-neutral-50 p-3">
              <p className="text-sm font-semibold">
                Chunk {part.index} of {file.totalChunks || file.parts.length}
                <span className="font-normal text-neutral-600">
                  {" "}
                  · {part.chars.toLocaleString()} characters
                  {part.status === "skipped" && " · already in the graph"}
                </span>
              </p>
              {part.status === "added" && (
                <ExtractionResult entities={part.entities} facts={part.facts} dropped={part.dropped_facts} unmapped={part.unmapped} small />
              )}
            </li>
          ))}
          {file.current && (
            <li className="flex flex-col gap-2 rounded-lg border border-dashed border-neutral-300 p-3">
              <p className="flex items-center gap-2 text-sm font-semibold">
                <LoaderCircle className="icon icon-sm animate-spin" aria-hidden />
                Chunk {file.current.index} of {file.totalChunks}
                <span className="font-normal text-neutral-600">
                  · {file.current.chars.toLocaleString()} characters → episode <code>{file.current.episode}</code>
                </span>
              </p>
              <p className="text-xs whitespace-pre-wrap text-neutral-600">{file.current.preview}…</p>
            </li>
          )}
        </ol>
      )}
    </li>
  );
}

export function DocumentsCard() {
  const [bucket, setBucket] = useState<string>(BUCKETS[0]);
  const [prefix, setPrefix] = useState("");
  const [limit, setLimit] = useState(5);
  const [groupId, setGroupId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listed, setListed] = useState<Listed | null>(null);
  const [files, setFiles] = useState<FileState[]>([]);
  const [log, setLog] = useState<LogLine[]>([]);
  const controller = useRef<AbortController | null>(null);

  const note = (text: string) => setLog((current) => [...current, { at: new Date().toLocaleTimeString(), text }]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    controller.current = new AbortController();
    setBusy(true);
    setError(null);
    setListed(null);
    setFiles([]);
    setLog([]);
    const body = { bucket, prefix, limit, ...groupBody(groupId) };
    const failure = await graphStream(
      "/documents/stream",
      body,
      (event) => {
        if (event.event === "listed") setListed(event);
        setFiles((current) => apply(current, event));
        note(describe(event));
      },
      controller.current.signal,
    );
    if (controller.current.signal.aborted) {
      setFiles(stopAll);
      note("Stopped. A chunk already sent to Graphiti finishes; nothing after it is added. Run again to continue.");
    }
    setError(failure);
    setBusy(false);
  }

  const finished = files.filter((f) => !["waiting", "running", "stopped"].includes(f.status)).length;
  const running = files.find((f) => f.status === "running");
  const runningShare = running?.totalChunks ? running.parts.length / running.totalChunks : 0;
  const progress = files.length ? Math.round(((finished + runningShare) / files.length) * 100) : 0;
  const added = files.flatMap((f) => f.parts).filter((p) => p.status === "added");
  const skipped = files.flatMap((f) => f.parts).length - added.length;

  return (
    <Card
      title="Add documents"
      note="Reads files from a Supabase Storage bucket, splits each into 8,000-character chunks and adds every chunk as an episode. Only organisations, funders, places, programmes, themes and their leaders are kept, and only the relationships between them the ontology allows. Chunks already in the graph are skipped."
    >
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <Field label="Bucket">
          <select className={selectClass} value={bucket} onChange={(e) => setBucket(e.target.value)}>
            {BUCKETS.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Prefix">
          <input className={inputClass} placeholder="orgs/12/" value={prefix} onChange={(e) => setPrefix(e.target.value)} />
        </Field>
        <Field label="Files">
          <input
            className={`${inputClass} w-20`}
            type="number"
            min={1}
            max={50}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
          />
        </Field>
        <Field label="Group">
          <input
            className={inputClass}
            placeholder={DEFAULT_GROUP}
            pattern="[a-zA-Z0-9_\-]+"
            title={GROUP_HINT}
            value={groupId}
            onChange={(e) => setGroupId(e.target.value)}
          />
        </Field>
        <button type="submit" className="btn btn-primary px-4 py-1.5" disabled={busy}>
          <Upload className="icon icon-sm" aria-hidden />
          {busy ? "Running…" : "Add documents"}
        </button>
        {busy && (
          <button
            type="button"
            className="btn btn-secondary px-4 py-1.5 text-terracotta-750"
            onClick={() => controller.current?.abort()}
          >
            <CircleStop className="icon icon-sm" aria-hidden />
            Stop
          </button>
        )}
      </form>
      <ErrorText error={error} />

      {log.length > 0 && (
        <div className="flex flex-col gap-4 border-t border-neutral-200 pt-4">
          {listed && (
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap justify-between gap-2 text-sm">
                <span>
                  {listed.found} files under <code>{listed.bucket}/{listed.prefix}</code> → group{" "}
                  <code>{listed.group_id}</code>
                </span>
                <span className="text-neutral-600">
                  {finished}/{files.length} files · {added.length} chunks added · {skipped} skipped ·{" "}
                  {added.reduce((n, p) => n + p.entities.length, 0)} entities ·{" "}
                  {added.reduce((n, p) => n + p.facts.length, 0)} facts kept ·{" "}
                  {added.reduce((n, p) => n + p.dropped_facts.length, 0)} dropped
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-neutral-100">
                <div className="h-full bg-accent-750 transition-all" style={{ width: `${progress}%` }} />
              </div>
            </div>
          )}

          <ol className="max-h-56 overflow-y-auto rounded-lg bg-neutral-50 p-3 font-mono text-xs">
            {log.map((line, i) => (
              <li key={i}>
                <span className="text-neutral-500">{line.at}</span> {line.text}
              </li>
            ))}
          </ol>

          {files.length > 0 && (
            <ul className="flex flex-col gap-2">
              {files.map((file) => (
                <FileRow key={file.key} file={file} />
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
