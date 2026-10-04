import Link from "next/link";
import { SignInButton } from "@/features/auth/sign-in-button";

// One entry point per destination. Ask Sangam is public: signed out it previews,
// signed in it is the workspace. Import is staff tooling and lives in the workspace.
const LINKS = [
  { id: "registry", label: "Registry", href: "/registry" },
  { id: "ask", label: "Ask Sangam", href: "/ask" },
  { id: "resources", label: "Resources", href: "/resources" },
] as const;

export type NavSection = "home" | (typeof LINKS)[number]["id"];

export function Nav({ current }: { current: NavSection }) {
  return (
    <nav
      className={
        "sticky top-0 z-50 h-(--nav-h) " +
        // Sage "liquid glass": the only translucent surface in the design system.
        "bg-[color-mix(in_srgb,var(--color-accent-2-700)_34%,white_66%)] backdrop-blur-[16px] backdrop-saturate-[1.4] " +
        "shadow-[0_1px_0_color-mix(in_srgb,var(--color-accent-2-700)_20%,transparent),0_8px_24px_-12px_color-mix(in_srgb,var(--color-accent-2-900)_25%,transparent)]"
      }
    >
      <div className="nav-inner mx-auto flex h-full max-w-(--page-max) items-center gap-3 px-(--page-pad) sm:gap-5">
        <Link
          href="/"
          className="mr-auto shrink-0 font-(family-name:--font-heading) text-2xl font-bold text-(--color-text) no-underline hover:no-underline"
        >
          sangam
        </Link>
        {/* Fixed height, so on a phone the links scroll sideways rather than wrap. */}
        <div className="flex min-w-0 items-center gap-3 overflow-x-auto whitespace-nowrap sm:gap-5">
          {LINKS.map((link) => (
            <Link
              key={link.id}
              href={link.href}
              className="nav-link text-sm font-semibold"
              aria-current={current === link.id ? "page" : undefined}
            >
              {link.label}
            </Link>
          ))}
        </div>
        <SignInButton />
      </div>
    </nav>
  );
}
