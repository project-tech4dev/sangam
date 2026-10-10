"use client";

import { useEffect, useState } from "react";
import { useInterrupt } from "@copilotkit/react-core/v2";
import { authHeaders } from "@/lib/api/auth-headers";
import type { ImportAccess, VaultFile } from "../lib/access";
import { proposedSources, sourcesDecision, type SourcesChoice } from "../lib/sourcePick";
import type { Workbook } from "../lib/types";
import { orgById, searchOrgs, vaultFilesOf, type VaultOrg } from "../lib/vaultFiles";
import { PauseSignal } from "./PauseSignal";

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

const VAULT_HINT = "Read privately, by a reader that cannot use the web. Only a funder's general facts are saved from them.";

function VaultChips({
  files,
  picked,
  onToggle,
  disabled,
  showOrg,
}: {
  files: VaultFile[];
  picked: (f: VaultFile) => boolean;
  onToggle: (f: VaultFile) => void;
  disabled: boolean;
  showOrg: boolean;
}) {
  return (
    <div className="import-chips">
      {files.map((f) => (
        <button
          key={f.id}
          type="button"
          className="import-chip import-file"
          aria-pressed={picked(f)}
          onClick={() => onToggle(f)}
          disabled={disabled}
        >
          {f.title || `Document ${f.id}`}
          {showOrg && <span className="import-hint"> · {f.orgName}</span>}
        </button>
      ))}
    </div>
  );
}

/** Staff: any organisation's Doc Vault, found by name, or opened on the one the agent proposed. */
function OrgVault({
  proposedOrg,
  picked,
  onToggle,
  disabled,
}: {
  proposedOrg: number | null;
  picked: (f: VaultFile) => boolean;
  onToggle: (f: VaultFile) => void;
  disabled: boolean;
}) {
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<VaultOrg[]>([]);
  const [org, setOrg] = useState<VaultOrg | null>(null);
  const [files, setFiles] = useState<VaultFile[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (proposedOrg === null) return;
    let cancelled = false;
    orgById(proposedOrg)
      .then((o) => !cancelled && setOrg(o))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [proposedOrg]);

  useEffect(() => {
    if (!org) return;
    let cancelled = false;
    vaultFilesOf(org)
      .then((found) => !cancelled && setFiles(found))
      .catch(() => {
        if (!cancelled) {
          setFiles([]);
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [org]);

  const q = query.trim();
  useEffect(() => {
    if (q.length < 2) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      searchOrgs(q)
        .then((found) => !cancelled && setMatches(found))
        .catch(() => !cancelled && setMatches([]));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [q]);

  function pick(o: VaultOrg) {
    setOrg(o);
    setFiles(null);
    setFailed(false);
    setQuery("");
    setMatches([]);
  }

  return (
    <div className="import-names">
      <span className="import-label">{org ? `Doc Vault: ${org.name}` : "An organisation's Doc Vault"}</span>
      <div className="import-form">
        <input
          className="input"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={org ? "Find another organisation" : "Find an organisation by name"}
          aria-label="Find an organisation's Doc Vault"
          disabled={disabled}
        />
      </div>
      {q.length >= 2 && matches.length > 0 && (
        <div className="import-chips">
          {matches.map((m) => (
            <button key={m.id} type="button" className="import-chip" onClick={() => pick(m)} disabled={disabled}>
              {m.name}
            </button>
          ))}
        </div>
      )}
      {org && files === null && <span className="muted">Looking in {org.name}&apos;s Doc Vault…</span>}
      {org && files !== null && files.length === 0 && (
        <span className="import-pick-text">
          {failed ? `Sangam couldn't list ${org.name}'s Doc Vault.` : `${org.name} has no private files.`}
        </span>
      )}
      {files !== null && files.length > 0 && (
        <>
          <VaultChips files={files} picked={picked} onToggle={onToggle} disabled={disabled} showOrg={false} />
          <span className="import-hint">{VAULT_HINT}</span>
        </>
      )}
    </div>
  );
}

/** Where should Sangam read from? One question before anything is read; the run reads only what is ticked. */
function Card({
  proposal,
  access,
  vaultFiles,
  onDecide,
}: {
  proposal: SourcesChoice;
  access: ImportAccess;
  vaultFiles: VaultFile[];
  onDecide: (choice: SourcesChoice) => void;
}) {
  const [web, setWeb] = useState(proposal.web);
  const [library, setLibrary] = useState(proposal.library);
  const [vaultDocs, setVaultDocs] = useState<number[]>(proposal.vault_docs);
  const [vaultOrg, setVaultOrg] = useState<number | null>(proposal.vault_org);
  const [staffPaths, setStaffPaths] = useState<string[]>(proposal.staff_paths);
  const [sent, setSent] = useState(false);
  const { files, failed } = useWorkbooks(access.staff);

  // One organisation's files per run: picking another's starts a new pick.
  function toggleVault(f: VaultFile) {
    const kept = vaultOrg === f.orgId ? vaultDocs : [];
    const next = toggled(kept, f.id);
    setVaultDocs(next);
    setVaultOrg(next.length ? f.orgId : null);
  }

  const picked = (f: VaultFile) => vaultOrg === f.orgId && vaultDocs.includes(f.id);
  const ownOrgs = new Set(vaultFiles.map((f) => f.orgId));

  const nothing = !web && !library && vaultDocs.length === 0 && staffPaths.length === 0;

  function decide(choice: SourcesChoice) {
    setSent(true);
    onDecide(choice);
  }

  return (
    <section className="import-pick" aria-label="Where Sangam reads from">
      <div className="import-head">
        <span className="card-kicker">Sangam needs your answer</span>
        <strong className="import-pick-title">Where should Sangam read from?</strong>
        <span className="import-pick-text">Nothing is opened until you choose. Sangam reads only what you tick.</span>
      </div>

      <ul className="import-files">
        <li>
          <Option
            checked={web}
            onChange={setWeb}
            disabled={sent}
            title="Public websites"
            note="Funders' and NGOs' own pages, filings and reports — only sites Sangam is allowed to read."
          />
        </li>
        <li>
          <Option
            checked={library}
            onChange={setLibrary}
            disabled={sent}
            title="Sangam's library"
            note="Public reports Sangam already holds about these organisations, read from its saved copies."
          />
        </li>
      </ul>

      {vaultFiles.length > 0 && (
        <div className="import-names">
          <span className="import-label">Your organisation&apos;s documents</span>
          <VaultChips
            files={vaultFiles}
            picked={picked}
            onToggle={toggleVault}
            disabled={sent}
            showOrg={access.orgs.length > 1}
          />
          <span className="import-hint">{VAULT_HINT}</span>
        </div>
      )}

      {access.staff && (
        <OrgVault
          proposedOrg={proposal.vault_org !== null && !ownOrgs.has(proposal.vault_org) ? proposal.vault_org : null}
          picked={picked}
          onToggle={toggleVault}
          disabled={sent}
        />
      )}

      {access.staff && (
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
                      checked={staffPaths.includes(f.path)}
                      onChange={() => setStaffPaths((prev) => toggled(prev, f.path))}
                      disabled={sent}
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

      <div className="import-pick-actions">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => decide({ web, library, vault_org: vaultOrg, vault_docs: vaultDocs, staff_paths: staffPaths })}
          disabled={sent || nothing}
        >
          Start reading
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => decide({ web: true, library: false, vault_org: null, vault_docs: [], staff_paths: [] })}
          disabled={sent}
        >
          Only public websites
        </button>
      </div>
    </section>
  );
}

/** Shows the sources question while the run is paused on choose_sources. */
export function SourcesCard({
  agentId,
  access,
  vaultFiles,
  onPaused,
}: {
  agentId: string;
  access: ImportAccess;
  vaultFiles: VaultFile[];
  onPaused: (paused: boolean) => void;
}) {
  return useInterrupt({
    agentId,
    renderInChat: false,
    enabled: (event) => proposedSources(event.value) !== null,
    render: ({ event, resolve }) => (
      <>
        <Card
          proposal={proposedSources(event.value)!}
          access={access}
          vaultFiles={vaultFiles}
          onDecide={(choice) => void resolve({ decisions: [sourcesDecision(choice)] })}
        />
        <PauseSignal onPaused={onPaused} />
      </>
    ),
  });
}
