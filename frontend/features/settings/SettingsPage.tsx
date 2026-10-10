import { apiGet } from "@/lib/api";
import { createClient } from "@/lib/supabase/server";
import { OrgMembersCard } from "./OrgMembersCard";
import type { OrgMember } from "./members-api";
import { StaffMembersCard, type OrgOption } from "./StaffMembersCard";

type Me = {
  id: string;
  is_staff: boolean;
  memberships: { org_id: number; org_name: string; role: string }[];
};

export async function SettingsPage() {
  const supabase = await createClient();
  // /api/me fails without a session, so it runs alongside getUser and only counts when there is a user.
  const [{ data }, maybeMe] = await Promise.all([
    supabase.auth.getUser(),
    apiGet<Me>("/api/me").catch(() => null),
  ]);
  const user = data.user;
  const me = user ? maybeMe : null;
  const adminOrgs = me && !me.is_staff ? me.memberships.filter((m) => m.role === "admin") : [];
  const [members, allOrgs] = await Promise.all([
    Promise.all(adminOrgs.map((m) => apiGet<OrgMember[]>(`/api/orgs/${m.org_id}/members`))),
    me?.is_staff ? apiGet<OrgOption[]>("/api/orgs") : Promise.resolve([] as OrgOption[]),
  ]);

  return (
    <div className="sangam-ui">
      <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-10">
        <h1 className="text-2xl font-semibold">Settings</h1>
        {user ? (
          <section className="rounded-lg border border-neutral-300 bg-white p-5">
            <h2 className="mb-3 text-lg font-semibold">Account</h2>
            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
              <dt className="text-neutral-600">Name</dt>
              <dd>{user.user_metadata?.full_name ?? "—"}</dd>
              <dt className="text-neutral-600">Email</dt>
              <dd>{user.email}</dd>
            </dl>
          </section>
        ) : null}
        {!user ? (
          <p className="text-sm text-neutral-700">Sign in to see your settings.</p>
        ) : me && !me.is_staff ? (
          <section className="rounded-lg border border-neutral-300 bg-white p-5">
            <h2 className="mb-3 text-lg font-semibold">My organisations</h2>
            {me.memberships.length === 0 ? (
              <p className="text-sm text-neutral-700">You don&apos;t belong to any organisation yet.</p>
            ) : (
              <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
                {me.memberships.map((m) => (
                  <div key={m.org_id} className="contents">
                    <dt>{m.org_name}</dt>
                    <dd className="text-neutral-600 capitalize">{m.role}</dd>
                  </div>
                ))}
              </dl>
            )}
          </section>
        ) : null}
        {me &&
          adminOrgs.map((m, i) => (
            <OrgMembersCard
              key={m.org_id}
              orgId={m.org_id}
              orgName={m.org_name}
              meId={me.id}
              initialMembers={members[i]}
              note="You manage this list because you are an admin of the organisation."
            />
          ))}
        {me?.is_staff && (
          <StaffMembersCard orgs={allOrgs.map((o) => ({ id: o.id, name: o.name }))} meId={me.id} />
        )}
      </main>
    </div>
  );
}
