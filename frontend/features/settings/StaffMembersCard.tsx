"use client";

import { useRef, useState } from "react";
import { OrgMembersList } from "./OrgMembersCard";
import { membersRequest, selectClass, type OrgMember } from "./members-api";

export type OrgOption = { id: number; name: string };

export function StaffMembersCard({ orgs, meId }: { orgs: OrgOption[]; meId: string }) {
  const [org, setOrg] = useState<OrgOption | null>(null);
  const [members, setMembers] = useState<OrgMember[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const picked = useRef<number | null>(null);

  async function pick(id: string) {
    const next = orgs.find((o) => String(o.id) === id) ?? null;
    setOrg(next);
    setMembers(null);
    setError(null);
    picked.current = next?.id ?? null;
    if (!next) return;
    const result = await membersRequest(next.id);
    // A slow answer for an organisation no longer picked must not land on the current one.
    if (picked.current !== next.id) return;
    if ("error" in result) setError(result.error);
    else setMembers(result.members);
  }

  return (
    <section className="flex flex-col gap-4 rounded-lg border border-neutral-300 bg-white p-5">
      <div>
        <h2 className="text-lg font-semibold">Organisation members</h2>
        <p className="text-sm text-neutral-600">
          Choose an organisation to manage its members. A person needs to have signed in to Sangam once before
          they can be added.
        </p>
      </div>
      <select
        aria-label="Organisation"
        className={`${selectClass} max-w-80`}
        value={org ? String(org.id) : ""}
        onChange={(e) => pick(e.target.value)}
      >
        <option value="">Choose an organisation</option>
        {orgs.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
      </select>
      {error && <p className="text-sm text-terracotta-750">{error}</p>}
      {org && members && (
        <div className="border-t border-neutral-200 pt-4">
          <OrgMembersList key={org.id} orgId={org.id} meId={meId} initialMembers={members} />
        </div>
      )}
    </section>
  );
}
