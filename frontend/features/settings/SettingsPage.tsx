import { createClient } from "@/lib/supabase/server";

export async function SettingsPage() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getUser();
  const user = data.user;

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
        ) : (
          <p className="text-sm text-neutral-700">Sign in to see your settings.</p>
        )}
      </main>
    </div>
  );
}
