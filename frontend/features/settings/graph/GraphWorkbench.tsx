"use client";

import { Search, Trash2, Upload } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { PillTabs } from "@/components/ui";
import { selectClass } from "../members-api";
import { DocumentsCard } from "./DocumentsCard";
import {
  graphRequest,
  type ClearResult,
  type EpisodeResult,
  type GraphGroup,
  type GraphStatus,
  type SearchResult,
} from "./graph-api";
import { Card, ErrorText, FactList, Field, GROUP_HINT, inputClass, Pills } from "./graph-ui";

const TABS = [
  { id: "episode", label: "Add episode" },
  { id: "documents", label: "Add documents" },
  { id: "search", label: "Search" },
  { id: "clear", label: "Clear" },
];

function useRequest<T>() {
  const [result, setResult] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(request: Promise<{ data: T } | { error: string }>) {
    setBusy(true);
    setError(null);
    setResult(null);
    const outcome = await request;
    if ("error" in outcome) setError(outcome.error);
    else setResult(outcome.data);
    setBusy(false);
  }

  return { result, error, busy, run };
}

function EpisodeCard() {
  const [text, setText] = useState("");
  const [name, setName] = useState("api-episode");
  const [groupId, setGroupId] = useState("");
  const { result, error, busy, run } = useRequest<EpisodeResult>();

  function submit(e: FormEvent) {
    e.preventDefault();
    run(graphRequest<EpisodeResult>("POST", "/episodes", { text, name, group_id: groupId || null }));
  }

  return (
    <Card title="Add episode" note="Paste text; Graphiti extracts entities and facts from it with one model call.">
      <form onSubmit={submit} className="flex flex-col gap-3">
        <textarea
          aria-label="Episode text"
          className="min-h-32 rounded-lg border border-neutral-300 p-3 text-sm"
          maxLength={20000}
          placeholder="Pratham runs reading camps in 300 villages of Assam, funded by the Tata Trusts since 2019."
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Name">
            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Group (optional)">
            <input
              className={inputClass}
              pattern="[a-zA-Z0-9_\-]+"
              title={GROUP_HINT}
              value={groupId}
              onChange={(e) => setGroupId(e.target.value)}
            />
          </Field>
          <button type="submit" className="btn btn-primary px-4 py-1.5" disabled={busy || !text.trim()}>
            <Upload className="icon icon-sm" aria-hidden />
            {busy ? "Extracting…" : "Add episode"}
          </button>
        </div>
      </form>
      <ErrorText error={error} />
      {result && (
        <div className="grid gap-4 border-t border-neutral-200 pt-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">Entities ({result.entities.length})</h3>
            <Pills items={result.entities} />
          </div>
          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">Facts ({result.facts.length})</h3>
            <FactList facts={result.facts} />
          </div>
        </div>
      )}
    </Card>
  );
}
function SearchCard() {
  const [query, setQuery] = useState("");
  const [groupId, setGroupId] = useState("");
  const { result, error, busy, run } = useRequest<SearchResult>();

  function submit(e: FormEvent) {
    e.preventDefault();
    run(graphRequest<SearchResult>("POST", "/search", { query, group_id: groupId || null, limit: 20 }));
  }

  return (
    <Card title="Search" note="Hybrid search over the facts in the graph. No model call.">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <Field label="Query">
          <input
            className={`${inputClass} w-72`}
            placeholder="Who funds education in Assam?"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </Field>
        <Field label="Group (optional)">
          <input
            className={inputClass}
            pattern="[a-zA-Z0-9_\-]+"
            title={GROUP_HINT}
            value={groupId}
            onChange={(e) => setGroupId(e.target.value)}
          />
        </Field>
        <button type="submit" className="btn btn-secondary px-4 py-1.5" disabled={busy || !query.trim()}>
          <Search className="icon icon-sm" aria-hidden />
          {busy ? "Searching…" : "Search"}
        </button>
      </form>
      <ErrorText error={error} />
      {result && (
        <div className="border-t border-neutral-200 pt-4">
          <FactList facts={result.facts.map((f) => f.fact)} />
        </div>
      )}
    </Card>
  );
}

function ClearCard() {
  const [groups, setGroups] = useState<GraphGroup[] | null>(null);
  const [groupsError, setGroupsError] = useState<string | null>(null);
  const [groupId, setGroupId] = useState("");
  const [armed, setArmed] = useState(false);
  const { result, error, busy, run } = useRequest<ClearResult>();

  function loadGroups() {
    graphRequest<GraphGroup[]>("GET", "/groups").then((outcome) => {
      setGroupsError("error" in outcome ? outcome.error : null);
      if (!("error" in outcome)) setGroups(outcome.data);
    });
  }

  useEffect(loadGroups, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!armed) return setArmed(true);
    setArmed(false);
    await run(graphRequest<ClearResult>("DELETE", groupId ? `?group_id=${encodeURIComponent(groupId)}` : ""));
    setGroupId("");
    loadGroups();
  }

  const total = groups?.reduce((n, g) => n + g.nodes, 0) ?? 0;

  return (
    <Card title="Clear" note="Deletes every node and fact in one group, or the whole graph.">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <Field label="Group">
          <select
            className={selectClass}
            value={groupId}
            disabled={!groups}
            onChange={(e) => {
              setGroupId(e.target.value);
              setArmed(false);
            }}
          >
            <option value="">Everything ({total} nodes)</option>
            {groups?.map((g) => (
              <option key={g.group_id} value={g.group_id} disabled={!g.group_id}>
                {g.group_id || "(no group: clear with everything)"} · {g.nodes} nodes, {g.episodes} episodes
              </option>
            ))}
          </select>
        </Field>
        <button type="submit" className="btn btn-secondary px-4 py-1.5 text-terracotta-750" disabled={busy || !groups}>
          <Trash2 className="icon icon-sm" aria-hidden />
          {armed ? (groupId ? `Confirm: delete ${groupId}` : "Confirm: delete the whole graph") : "Clear"}
        </button>
      </form>
      {groups?.length === 0 && <p className="text-sm text-neutral-600">The graph is empty.</p>}
      <ErrorText error={groupsError ?? error} />
      {result && (
        <p className="text-sm">
          Deleted {result.nodes_deleted} nodes{result.group_id ? ` from ${result.group_id}` : ""}.
        </p>
      )}
    </Card>
  );
}

export function GraphWorkbench({ status }: { status: GraphStatus | null }) {
  const [tab, setTab] = useState(TABS[0].id);

  if (!status?.enabled) {
    return (
      <p className="rounded-lg border border-neutral-300 bg-white p-5 text-sm text-neutral-700">
        The knowledge graph is off: {status?.reason ?? "could not reach Sangam"}.
      </p>
    );
  }
  return (
    <>
      <PillTabs tabs={TABS} active={tab} onPick={setTab} />
      {tab === "episode" && <EpisodeCard />}
      {tab === "documents" && <DocumentsCard />}
      {tab === "search" && <SearchCard />}
      {tab === "clear" && <ClearCard />}
    </>
  );
}
