"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ROLES, membersRequest, selectClass, type OrgMember } from "./members-api";

type ListProps = { orgId: number; meId: string; initialMembers: OrgMember[] };

export function OrgMembersCard({ orgName, note, ...list }: ListProps & { orgName: string; note: string }) {
  return (
    <section className="flex flex-col gap-4 rounded-lg border border-neutral-300 bg-white p-5">
      <div>
        <h2 className="text-lg font-semibold">Members of {orgName}</h2>
        <p className="text-sm text-neutral-600">{note}</p>
      </div>
      <OrgMembersList {...list} />
    </section>
  );
}

function RoleSelect({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  disabled?: boolean;
  onChange: (role: string) => void;
}) {
  return (
    <select
      aria-label={label}
      className={`${selectClass} capitalize`}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    >
      {ROLES.map((r) => (
        <option key={r} value={r}>
          {r}
        </option>
      ))}
    </select>
  );
}

export function OrgMembersList({ orgId, meId, initialMembers }: ListProps) {
  const [members, setMembers] = useState(initialMembers);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<string>("member");

  async function send(method: string, path: string, body?: object): Promise<boolean> {
    setBusy(true);
    setError(null);
    const result = await membersRequest(orgId, method, path, body);
    setBusy(false);
    if ("error" in result) {
      setError(result.error);
      return false;
    }
    setMembers(result.members);
    return true;
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    if (await send("POST", "", { email, role })) setEmail("");
  }

  return (
    <div className="flex flex-col gap-4">
      {members.length === 0 ? (
        <p className="text-sm text-neutral-600">No members yet. Add the first one below.</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-neutral-300">
              <th className="px-2 py-1.5 font-medium text-neutral-700">Name</th>
              <th className="px-2 py-1.5 font-medium text-neutral-700">Email</th>
              <th className="px-2 py-1.5 font-medium text-neutral-700">Role</th>
              <th className="px-2 py-1.5" />
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.user_id} className="border-b border-neutral-200 last:border-0">
                <td className="px-2 py-1.5">
                  {m.display_name ?? "—"}
                  {m.user_id === meId && <span className="text-neutral-600"> (you)</span>}
                </td>
                <td className="px-2 py-1.5">{m.email}</td>
                <td className="px-2 py-1.5">
                  <RoleSelect
                    label={`Role of ${m.email}`}
                    value={m.role}
                    disabled={busy}
                    onChange={(next) => send("PATCH", `/${m.user_id}`, { role: next })}
                  />
                </td>
                <td className="px-2 py-1.5 text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    className="text-terracotta-750"
                    onClick={() => send("DELETE", `/${m.user_id}`)}
                  >
                    Remove
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <form onSubmit={add} className="flex flex-wrap items-center gap-2">
        <Input
          type="email"
          required
          placeholder="Email of a Sangam user"
          aria-label="Email of the person to add"
          className="h-8 max-w-64"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <RoleSelect label="Role" value={role} onChange={setRole} />
        <Button type="submit" size="sm" disabled={busy}>
          Add member
        </Button>
      </form>

      {error && <p className="text-sm text-terracotta-750">{error}</p>}
    </div>
  );
}
