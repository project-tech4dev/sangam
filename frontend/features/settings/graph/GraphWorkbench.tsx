"use client";

import { DatabaseZap, Search, Trash2, Upload } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { PillTabs } from "@/components/ui";
import { selectClass } from "../members-api";
import { DocumentsCard } from "./DocumentsCard";
import {
  DEFAULT_GROUP,
  ENTITY_TYPES,
  graphRequest,
  groupBody,
  type CatalogResult,
  type ClearResult,
  type EpisodeResult,
  type GraphGroup,
  type GraphStatus,
  type GraphEntity,
  type SearchResult,
} from "./graph-api";
import { Card, ErrorText, ExtractionResult, Field, GROUP_HINT, inputClass } from "./graph-ui";

const TABS = [
  { id: "episode", label: "Add episode" },
  { id: "documents", label: "Add documents" },
  { id: "catalog", label: "Sync catalog" },
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
    run(graphRequest<EpisodeResult>("POST", "/episodes", { text, name, ...groupBody(groupId) }));
  }

  return (
    <Card
      title="Add episode"
      note="Paste text; Graphiti extracts organisations, funders, places, programmes, themes and leaders from it, and only the relationships the ontology allows between them."
    >
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
          <Field label="Group">
            <input
              className={inputClass}
              pattern="[a-zA-Z0-9_\-]+"
              placeholder={DEFAULT_GROUP}
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
        <div className="border-t border-neutral-200 pt-4">
          <ExtractionResult entities={result.entities} facts={result.facts} dropped={result.dropped_facts} unmapped={result.unmapped} />
        </div>
      )}
    </Card>
  );
}

function endLabel(end: GraphEntity | null) {
  if (!end) return "?";
  return `${end.name} (${end.type}${end.sangam_id ? ` ✓ ${end.sangam_id}` : ""})`;
}

function SearchCard() {
  const [query, setQuery] = useState("");
  const [groupId, setGroupId] = useState("");
  const [types, setTypes] = useState<string[]>([]);
  const { result, error, busy, run } = useRequest<SearchResult>();

  function submit(e: FormEvent) {
    e.preventDefault();
    run(
      graphRequest<SearchResult>("POST", "/search", {
        query,
        group_id: groupId || null,
        limit: 20,
        types: types.length ? types : null,
      }),
    );
  }

  function toggle(type: string) {
    setTypes((current) => (current.includes(type) ? current.filter((t) => t !== type) : [...current, type]));
  }

  return (
    <Card
      title="Search"
      note="Hybrid search over the facts in the graph. No model call. Pick types to keep only facts whose two ends are both one of them."
    >
      <form onSubmit={submit} className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Query">
            <input
              className={`${inputClass} w-72`}
              placeholder="Who funds education in Assam?"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </Field>
          <Field label="Group (empty = all groups)">
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
        </div>
        <fieldset className="flex flex-wrap gap-3 text-sm">
          <legend className="mb-1 text-neutral-600">Entity types</legend>
          {ENTITY_TYPES.map((type) => (
            <label key={type} className="flex items-center gap-1.5">
              <input type="checkbox" checked={types.includes(type)} onChange={() => toggle(type)} />
              {type}
            </label>
          ))}
        </fieldset>
      </form>
      <ErrorText error={error} />
      {result && (
        <div className="border-t border-neutral-200 pt-4">
          {result.facts.length === 0 ? (
            <p className="text-sm text-neutral-500">No facts found.</p>
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {result.facts.map((f) => (
                <li key={f.uuid} className="flex flex-col gap-0.5 rounded-lg bg-neutral-50 p-3">
                  <span>{f.fact}</span>
                  <span className="text-xs text-neutral-600">
                    {endLabel(f.source)} → <code>{f.name}</code> → {endLabel(f.target)}
                    {f.invalid_at ? ` · ended ${new Date(f.invalid_at).toLocaleDateString()}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

function CatalogCard() {
  const [groupId, setGroupId] = useState("");
  const { result, error, busy, run } = useRequest<CatalogResult>();

  function submit(e: FormEvent) {
    e.preventDefault();
    run(graphRequest<CatalogResult>("POST", "/catalog", groupBody(groupId)));
  }

  return (
    <Card
      title="Sync catalog"
      note="Writes Sangam's organisations, funders, places, programmes and themes into a group as typed nodes, with their links as relationships. No model call, only embeddings. Add documents to the same group so what they mention merges into these records."
    >
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <Field label="Group">
          <input
            className={inputClass}
            pattern="[a-zA-Z0-9_\-]+"
            placeholder={DEFAULT_GROUP}
            title={GROUP_HINT}
            value={groupId}
            onChange={(e) => setGroupId(e.target.value)}
          />
        </Field>
        <button type="submit" className="btn btn-primary px-4 py-1.5" disabled={busy}>
          <DatabaseZap className="icon icon-sm" aria-hidden />
          {busy ? "Syncing…" : "Sync catalog"}
        </button>
      </form>
      <ErrorText error={error} />
      {result && (
        <div className="flex flex-col gap-3 border-t border-neutral-200 pt-4 text-sm">
          <p>
            Group <code>{result.group_id}</code>: {result.nodes} nodes ({result.added_nodes} new,{" "}
            {result.removed_nodes} removed) and {result.edges} relationships ({result.added_edges} new,{" "}
            {result.removed_edges} removed).
          </p>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1">
            {Object.entries(result.by_type).map(([type, count]) => (
              <div key={type} className="contents">
                <dt className="text-neutral-600">{type}</dt>
                <dd>{count}</dd>
              </div>
            ))}
          </dl>
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
      {tab === "catalog" && <CatalogCard />}
      {tab === "search" && <SearchCard />}
      {tab === "clear" && <ClearCard />}
    </>
  );
}
