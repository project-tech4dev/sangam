import Link from "next/link";

/** The line under every Ask composer, signed in or not: answers need checking, and where the privacy terms are. */
export function ComposerNotice() {
  return (
    <div
      className="muted"
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: "4px 12px",
        borderTop: "1px solid var(--color-divider)",
        paddingTop: 10,
        fontSize: "var(--fs-xs)",
      }}
    >
      <span>AI can make mistakes; verify all responses. Early access: features are evolving.</span>
      <span aria-hidden className="muted-2">|</span>
      <Link href="/terms#t-collect" className="muted" style={{ textDecoration: "underline" }}>
        Privacy policy
      </Link>
    </div>
  );
}
