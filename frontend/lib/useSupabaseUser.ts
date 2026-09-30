"use client";

import type { User } from "@supabase/supabase-js";
import { useEffect, useState } from "react";
import { createClient } from "@/utils/supabase/client";

/**
 * The signed-in Supabase user, kept live across sign-in and sign-out.
 * `undefined` while the session is still being read, so callers can render nothing
 * instead of flashing the wrong state; `null` when signed out or when
 * NEXT_PUBLIC_SUPABASE_* are unset.
 */
export function useSupabaseUser(): User | null | undefined {
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    let supabase: ReturnType<typeof createClient>;
    try {
      supabase = createClient();
    } catch {
      setUser(null);
      return;
    }
    supabase.auth.getUser().then(({ data }) => setUser(data.user ?? null));
    const { data } = supabase.auth.onAuthStateChange((_event, session) => setUser(session?.user ?? null));
    return () => data.subscription.unsubscribe();
  }, []);

  return user;
}

// Google's profile lands in user_metadata; fall back to the email when it has no name.
export function displayName(user: User): string {
  const meta = user.user_metadata ?? {};
  return meta.full_name ?? meta.name ?? user.email ?? "Signed in";
}

export function initialsOf(user: User): string {
  const words = displayName(user).split(/[\s@.]+/).filter(Boolean);
  return words.slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";
}

export async function signOut(): Promise<void> {
  await createClient().auth.signOut();
}
