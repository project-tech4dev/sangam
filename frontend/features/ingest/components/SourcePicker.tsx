"use client";

import { useEffect, useState } from "react";
import { authHeaders } from "@/lib/api/auth-headers";
import type { VaultFile } from "../lib/access";
import type { SourcesChoice } from "../lib/sourcePick";
import type { Workbook } from "../lib/types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";
const STAFF_BUCKET = "staff-sources";

/** The team's spreadsheets, for staff to tick; null while loading, [] when there are none or listing failed. */
function useWorkbooks(enabled: boolean): { files: Workbook[] | null; failed: boolean } {
  const [files, setFiles] = useState<Workbook[] | null>(enabled ? null : []);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/ingest/workbooks?bucket=${STAFF_BUCKET}`, { headers: await authHeaders() });
        if (!res.ok) throw new Error(String(res.status));
        const found: Workbook[] = await res.json();
        if (!cancelled) setFiles(found);
      } catch {
        if (!cancelled) {
          setFiles([]);
          setFailed(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  return { files, failed };
}

function Option({
  checked,
  onChange,
  title,
  note,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  title: string;
  note: string;
  disabled: boolean;
}) {
  return (
    <label className="import-file">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} disabled={disabled} />
      <span className="import-file-name">
        <strong>{title}</strong>
        <span>{note}</span>
      </span>
    </label>
  );
}

function toggled<T>(list: T[], item: T): T[] {
  return list.includes(item) ? list.filter((i) => i !== item) : [...list, item];
}

/** Where a run may read from: websites, the library, the person's own orgs' Doc Vault files, and staff spreadsheets. */
export function SourcePicker({
  value,
  onChange,
  staff,
  vaultFiles,
  showOrg,
  disabled = false,
}: {
  value: SourcesChoice;
  onChange: (next: SourcesChoice) => void;
  staff: boolean;
  vaultFiles: VaultFile[];
  showOrg: boolean;
  disabled?: boolean;
}) {
  const { files, failed } = useWorkbooks(staff);

  // One organisation's files per run: picking another's starts a new pick.
  function toggleVault(f: VaultFile) {
    const kept = value.vault_org === f.orgId ? value.vault_docs : [];
    const next = toggled(kept, f.id);
    onChange({ ...value, vault_docs: next, vault_org: next.length ? f.orgId : null });
  }

  return (
    <>
      <ul className="import-files">
        <li>
          <Option
            checked={value.web}
            onChange={(web) => onChange({ ...value, web })}
            disabled={disabled}
            title="Public websites"
            note="Funders' and NGOs' own pages, filings and reports — only sites Sangam is allowed to read."
          />
        </li>
        <li>
          <Option
            checked={value.library}
            onChange={(library) => onChange({ ...value, library })}
            disabled={disabled}
            title="Sangam's library"
            note="Public reports Sangam already holds about these organisations, read from its saved copies."
          />
        </li>
      </ul>

      {vaultFiles.length > 0 && (
        <div className="import-names">
          <span className="import-label">Your organisation&apos;s documents</span>
          <div className="import-chips">
            {vaultFiles.map((f) => (
              <button
                key={f.id}
                type="button"
                className="import-chip import-file"
                aria-pressed={value.vault_org === f.orgId && value.vault_docs.includes(f.id)}
                onClick={() => toggleVault(f)}
                disabled={disabled}
              >
                {f.title || `Document ${f.id}`}
                {showOrg && <span className="import-hint"> · {f.orgName}</span>}
              </button>
            ))}
          </div>
          <span className="import-hint">
            Read privately, by a reader that cannot use the web. Only a funder&apos;s general facts are saved from them.
          </span>
        </div>
      )}

      {staff && (
        <div className="import-names">
          <span className="import-label">Team spreadsheets</span>
          {files === null && <span className="muted">Looking in your team&apos;s files…</span>}
          {files !== null && files.length === 0 && (
            <span className="import-pick-text">
              {failed ? "Sangam couldn't list the team's spreadsheets." : "There are no team spreadsheets yet."}
            </span>
          )}
          {files !== null && files.length > 0 && (
            <ul className="import-files">
              {files.map((f) => (
                <li key={f.path}>
                  <label className="import-file">
                    <input
                      type="checkbox"
                      checked={value.staff_paths.includes(f.path)}
                      onChange={() => onChange({ ...value, staff_paths: toggled(value.staff_paths, f.path) })}
                      disabled={disabled}
                    />
                    <span className="import-file-name">
                      <strong>{f.name}</strong>
                      <span>{[f.folder_label, f.updated_at && `added ${f.updated_at}`].filter(Boolean).join(" · ")}</span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </>
  );
}
