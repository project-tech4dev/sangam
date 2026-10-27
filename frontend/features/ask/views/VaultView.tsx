"use client";

import { useEffect, useState } from "react";
import { Tag } from "@/components/ui";
import { authHeaders } from "@/lib/api/auth-headers";
import { API } from "../lib/rest";
import { hostOf } from "../lib/sources";
import { type Doc, uploadToVault } from "../lib/vault";

export function VaultView({ orgs }: { orgs: { id: number; slug: string; name: string }[] }) {
  const [orgSlug, setOrgSlug] = useState(orgs[0]?.slug ?? "");
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!orgSlug) return;
    setDocs(null);
    authHeaders()
      .then((headers) => fetch(`${API}/api/documents?org=${orgSlug}&limit=100`, { headers }))
      .then((res) => (res.ok ? res.json() : { items: [] }))
      .then((page) => setDocs(page.items ?? []))
      .catch(() => setDocs([]));
  }, [orgSlug, reload]);

  async function onPick(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";  // so the same file can be retried after a failure
    if (!file || !orgSlug) return;
    setBusy(true);
    setProblem(null);
    try {
      await uploadToVault(orgSlug, file);
      setReload((n) => n + 1);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="view">
      <div className="fm-head">
        <div className="fm-head-text">
          <div className="eyebrow">Doc vault</div>
          <h2 className="view-title">Documents in the base, per organisation</h2>
        </div>
        <label className="pill vault-upload" data-busy={busy} data-off={!orgSlug}>
          {busy ? "Uploading…" : "Upload a document"}
          <input type="file" onChange={onPick} disabled={busy || !orgSlug} hidden />
        </label>
      </div>
      {problem ? (
        <div className="card" role="alert">
          <div className="card-title">Upload failed</div>
          <div className="card-body">{problem}</div>
        </div>
      ) : null}
      <div className="vault-orgs">
        {orgs.map((org) => (
          <button key={org.id} className="pill" data-active={orgSlug === org.slug} onClick={() => setOrgSlug(org.slug)}>
            {org.name}
          </button>
        ))}
      </div>
      {docs === null ? (
        <div className="muted">Loading…</div>
      ) : docs.length === 0 ? (
        <div className="card">
          <div className="card-title">No documents linked yet</div>
          <div className="card-body">
            The corpus holds 96 documents, but none are linked to this organisation yet — linking
            happens during vetting.
          </div>
        </div>
      ) : (
        <div className="card vault-list">
          {docs.map((doc) => (
            <div key={doc.id} className="vault-row">
              <span className="vault-type">{(doc.doc_type ?? "DOC").slice(0, 12).toUpperCase()}</span>
              <div className="vault-text">
                <div className="vault-name">{docName(doc)}</div>
                <div className="muted-2 vault-meta">
                  {doc.source_name ?? "unknown source"}
                  {doc.fetched_at ? ` · ${new Date(doc.fetched_at).toLocaleDateString("en-IN")}` : ""}
                </div>
              </div>
              <Tag tone="accent-2">In base</Tag>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function docName(doc: Doc): string {
  return doc.title || doc.source_name || (doc.source_url ? hostOf(doc.source_url) : "") || "Untitled document";
}
