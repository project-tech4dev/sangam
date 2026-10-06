"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { authHeaders } from "@/lib/api/auth-headers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

const ROLES = ["admin", "member", "steward"] as const;

export type OrgMember = { user_id: string; display_name: string | null; email: string; role: string };

const selectClass = "h-8 rounded-full border border-neutral-300 bg-white px-2 text-sm capitalize";

export function OrgMembersCard({
  orgId,
  orgName,
  meId,
  initialMembers,
}: {
  orgId: number;
  orgName: string;
  meId: string;
  initialMembers: OrgMember[];
}) {
  const [members, setMembers] = useState(initialMembers);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<string>("member");

  async function send(method: string, path: string, body?: object): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/orgs/${orgId}/members${path}`, {
        method,
        headers: { ...(await authHeaders()), "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      const payload = await res.json();
      if (!res.ok) {
        setError(typeof payload.detail === "string" ? payload.detail : "Something went wrong.");
        return false;
      }
      setMembers(payload);
      return true;
    } catch {
      setError("Could not reach Sangam. Try again.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    if (await send("POST", "", { email, role })) setEmail("");
  }

  return (
    <section className="flex flex-col gap-4 rounded-lg border border-neutral-300 bg-white p-5">
      <div>
        <h2 className="text-lg font-semibold">Members of {orgName}</h2>
        <p className="text-sm text-neutral-600">You manage this list because you are an admin of the organisation.</p>
      </div>

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
                <select
                  aria-label={`Role of ${m.email}`}
                  className={selectClass}
                  value={m.role}
                  disabled={busy}
                  onChange={(e) => send("PATCH", `/${m.user_id}`, { role: e.target.value })}
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
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
        <select aria-label="Role" className={selectClass} value={role} onChange={(e) => setRole(e.target.value)}>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <Button type="submit" size="sm" disabled={busy}>
          Add member
        </Button>
      </form>

      {error && <p className="text-sm text-terracotta-750">{error}</p>}
    </section>
  );
}
