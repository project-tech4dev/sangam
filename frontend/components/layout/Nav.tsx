import Link from "next/link";

const LINKS = [
  { id: "registry", label: "Registry", href: "/registry" },
  { id: "ask", label: "Ask Sangam", href: "/ask" },
  { id: "import", label: "Import", href: "/import" },
  { id: "resources", label: "Resources", href: "/resources" },
] as const;

export function Nav({ current }: { current: "home" | "registry" | "ask" | "import" | "resources" }) {
  return (
    <nav
      style={{
        position: "sticky",
        top: 0,
        zIndex: 50,
        background: "color-mix(in srgb, var(--color-accent-2-100) 72%, transparent)",
        backdropFilter: "blur(16px) saturate(1.4)",
        WebkitBackdropFilter: "blur(16px) saturate(1.4)",
        borderBottom: "1px solid var(--color-divider)",
      }}
    >
      <div
        style={{
          maxWidth: "var(--page-max)",
          margin: "0 auto",
          padding: "14px var(--page-pad)",
          display: "flex",
          alignItems: "center",
          gap: "12px 20px",
          flexWrap: "wrap",
        }}
      >
        <Link
          href="/registry"
          style={{
            fontFamily: "var(--font-heading)",
            fontSize: 22,
            fontWeight: 700,
            color: "var(--color-accent-2-900)",
            textDecoration: "none",
            marginRight: "auto",
          }}
        >
          sangam
        </Link>
        {LINKS.map((link) => (
          <Link
            key={link.id}
            href={link.href}
            style={{
              fontSize: 13.5,
              fontWeight: 700,
              textDecoration: "none",
              color: current === link.id ? "var(--color-accent-900)" : "var(--color-text)",
            }}
          >
            {link.label}
          </Link>
        ))}
        <Link href="/ask" className="btn btn-primary" style={{ padding: "8px 16px" }}>
          Ask Sangam
        </Link>
      </div>
    </nav>
  );
}
