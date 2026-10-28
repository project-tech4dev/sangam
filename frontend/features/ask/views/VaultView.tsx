"use client";

import { useEffect, useState } from "react";
import { Tag } from "@/components/ui";
import { authHeaders } from "@/lib/api/auth-headers";
import { API } from "../lib/rest";
import { hostOf } from "../lib/sources";
import { type Doc, deleteFromVault, uploadToVault } from "../lib/vault";

type Problem = { title: string; body: string };

export function VaultView({ orgs, isStaff = false }: { orgs: { id: number; slug: string; name: string }[]; isStaff?: boolean }) {
  const [orgSlug, setOrgSlug] = useState(orgs[0]?.slug ?? "");
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
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
    setNotice(null);
    try {
      await uploadToVault(orgSlug, file);
      setReload((n) => n + 1);
    } catch (error) {
      setProblem({ title: "Upload failed", body: error instanceof Error ? error.message : "Upload failed." });
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(doc: Doc) {
    if (!window.confirm(`Delete "${docName(doc)}"? The file and its record are removed for good.`)) return;
    setDeleting(doc.id);
    setProblem(null);
    setNotice(null);
    try {
      await deleteFromVault(doc.id);
  
      setDocs((current) => current?.filter((d) => d.id !== doc.id) ?? current);
      setNotice("Document deleted successfully.");
    } catch (error) {
      setProblem({ title: "Delete failed", body: error instanceof Error ? error.message : "The document could not be deleted. Please try again." });
    } finally {
      setDeleting(null);
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
          <div className="card-title">{problem.title}</div>
          <div className="card-body">{problem.body}</div>
        </div>
      ) : null}
      {notice ? (
        <div className="card" role="status">
          <div className="card-body">{notice}</div>
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
              {isStaff && doc.doc_type === "vault_upload" ? (
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => void onDelete(doc)}
                  disabled={deleting !== null}
                  aria-label={`Delete ${docName(doc)}`}
                >
                  {deleting === doc.id ? "Deleting…" : "Delete"}
                </button>
              ) : null}
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
