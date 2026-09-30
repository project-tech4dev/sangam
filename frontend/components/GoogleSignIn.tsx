"use client";

import { useEffect, useRef, useState } from "react";
import { createClient } from "@/utils/supabase/client";
import { displayName, initialsOf, signOut, useSupabaseUser } from "@/lib/useSupabaseUser";

/** The initials circle the prototype uses for the signed-in user. */
export function UserAvatar({ initials, size = 30 }: { initials: string; size?: number }) {
  return (
    <div
      aria-hidden
      style={{
        width: size,
        height: size,
        flex: "none",
        borderRadius: "50%",
        background: "var(--color-accent-600)",
        color: "var(--color-bg)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "var(--font-heading)",
        fontSize: "var(--fs-xs)",
      }}
    >
      {initials}
    </div>
  );
}

// "Sign in with Google": hands off to Google via Supabase, which returns the user to
// /auth/callback to finish the sign-in. The redirect URL carries no query string, so it
// matches the exact entry in Supabase's Redirect URLs allow-list; the callback then goes to "/".
// Once signed in, becomes the prototype's user menu: avatar and name, opening onto sign-out.
export function GoogleSignIn() {
  const user = useSupabaseUser();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close the menu on a click outside it or on Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  async function signIn() {
    setPending(true);
    setError(null);
    try {
      const supabase = createClient();
      const redirectTo = `${window.location.origin}/auth/callback`;
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo },
      });
      // On success the browser is already navigating to Google.
      if (error) throw error;
    } catch (err) {
      // Also reached when NEXT_PUBLIC_SUPABASE_* are unset: sign-in is unavailable, nothing else breaks.
      setError(err instanceof Error ? err.message : "Sign-in is unavailable right now.");
      setPending(false);
    }
  }

  async function logOut() {
    setMenuOpen(false);
    await signOut();
  }

  if (user === undefined) return null;

  if (user) {
    const name = displayName(user);
    return (
      <div ref={menuRef} style={{ position: "relative" }}>
        <button
          type="button"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            border: "none",
            background: "transparent",
            cursor: "pointer",
            padding: "4px 6px",
            borderRadius: "var(--radius-md)",
            fontFamily: "var(--font-body)",
          }}
        >
          <UserAvatar initials={initialsOf(user)} />
          <span style={{ fontSize: "var(--fs-sm)", color: "var(--color-text)" }}>{name}</span>
        </button>
        {menuOpen && (
          <div
            role="menu"
            style={{
              position: "absolute",
              top: "calc(100% + 8px)",
              right: 0,
              width: 200,
              background: "var(--color-bg)",
              border: "1px solid var(--color-divider)",
              borderRadius: "var(--radius-md)",
              boxShadow: "var(--shadow-md)",
              padding: 8,
              zIndex: 50,
            }}
          >
            <div style={{ padding: "8px 10px", fontSize: "var(--fs-xs)", color: "var(--color-neutral-700)", overflowWrap: "anywhere" }}>
              Signed in — {user.email ?? name}
            </div>
            <button
              type="button"
              role="menuitem"
              onClick={logOut}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "9px 10px",
                borderRadius: "var(--radius-sm)",
                border: "none",
                background: "transparent",
                cursor: "pointer",
                fontSize: "var(--fs-sm)",
                color: "var(--color-accent-700)",
                fontFamily: "var(--font-body)",
              }}
            >
              Log out
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div>
      <button type="button" className="btn btn-primary" onClick={signIn} disabled={pending}>
        {pending ? "Redirecting…" : "Sign in with Google"}
      </button>
      {error && (
        <p style={{ color: "var(--color-bad)", fontSize: "var(--fs-xs)", marginTop: 6 }}>{error}</p>
      )}
    </div>
  );
}
