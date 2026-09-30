import { createBrowserClient } from "@supabase/ssr";

// Supabase from the browser (client components). NEXT_PUBLIC_* values are inlined at
// build time, so changing them needs a rebuild, not just an env edit.
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
