"use client";

import { useEffect, useState } from "react";
import { Tag } from "@/components/ui";
import { authHeaders } from "@/lib/api/auth-headers";
import { API } from "../lib/rest";
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
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div className="eyebrow">Doc vault</div>
          <h2 style={{ fontSize: "var(--fs-lg)" }}>Documents in the base, per organisation</h2>
        </div>
        <label className="pill" style={{ cursor: busy ? "wait" : "pointer", opacity: orgSlug ? 1 : 0.5 }}>
          {busy ? "Uploading…" : "Upload a document"}
          <input type="file" onChange={onPick} disabled={busy || !orgSlug} style={{ display: "none" }} />
        </label>
      </div>
      {problem ? (
        <div className="card" role="alert">
          <div className="card-title">Upload failed</div>
          <div className="card-body">{problem}</div>
        </div>
      ) : null}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
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
        <div className="card" style={{ gap: 0, padding: 0 }}>
          {docs.map((doc) => (
            <div
              key={doc.id}
              style={{ display: "flex", gap: 12, alignItems: "center", padding: "12px 18px", borderBottom: "1px solid var(--color-divider)" }}
            >
              <span
                style={{ fontSize: "var(--fs-xs)", fontWeight: 700, background: "var(--color-neutral-200)", borderRadius: 6, padding: "3px 7px", color: "var(--color-neutral-700)" }}
              >
                {(doc.doc_type ?? "DOC").slice(0, 12).toUpperCase()}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: "var(--fs-sm)", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {doc.title ?? "Untitled document"}
                </div>
                <div className="muted-2" style={{ fontSize: "var(--fs-xs)" }}>
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
