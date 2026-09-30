import { NextResponse } from "next/server";
import { createClient } from "@/utils/supabase/server";

// Google sends the user back here with a one-time ?code=. Exchanging it for a session
// sets the Supabase auth cookies, then the user goes on to ?next= (default "/").
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/";
  // Only same-site paths, so the callback cannot be used to redirect somewhere else.
  const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/";

  if (code) {
    try {
      const supabase = await createClient();
      const { error } = await supabase.auth.exchangeCodeForSession(code);
      if (!error) {
        return NextResponse.redirect(`${origin}${safeNext}`);
      }
    } catch {
      // Supabase not configured (NEXT_PUBLIC_SUPABASE_* unset): fall through to the error redirect.
    }
  }

  return NextResponse.redirect(`${origin}/?auth_error=1`);
}
