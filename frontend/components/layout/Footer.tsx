"use client";

import { usePathname } from "next/navigation";

// The prototype's site footer (Sangam Prototype.html). "Terms & Privacy" is plain text
// until those pages exist.
export function Footer() {
  const pathname = usePathname() ?? "/";
  if (pathname.startsWith("/ask")) return null; // the workspace owns the whole screen
  return (
    <footer
      style={{
        marginTop: 64,
        padding: "36px 0",
        background: "var(--color-accent-2-900)",
        color: "var(--color-neutral-200)",
      }}
    >
      <div
        style={{
          maxWidth: "var(--page-max)",
          margin: "0 auto",
          padding: "0 var(--page-pad)",
          display: "flex",
          flexWrap: "wrap",
          gap: 20,
          alignItems: "baseline",
          justifyContent: "space-between",
          fontSize: "var(--fs-sm)",
        }}
      >
        <div style={{ display: "flex", gap: 22, color: "var(--color-neutral-300)" }}>Terms &amp; Privacy</div>
        <div style={{ opacity: 0.7 }}>© 2026 All rights reserved.</div>
      </div>
    </footer>
  );
}
