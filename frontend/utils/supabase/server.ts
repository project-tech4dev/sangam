import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

// Supabase on the server (server components, route handlers). The session lives in
// cookies, so this reads and writes them through Next's cookie store.
export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          } catch {
            // Server components cannot set cookies. Safe to ignore when a route handler
            // or middleware refreshes the session instead.
          }
        },
      },
    }
  );
}
