"use client";

import { usePathname } from "next/navigation";
import { Nav } from "./Nav";

// First prefix that matches wins, so /orgs and /funders read as Registry.
const SECTIONS = [
  ["/import", "import"],
  ["/registry", "registry"],
  ["/orgs", "registry"],
  ["/funders", "registry"],
  ["/resources", "resources"],
  ["/methodology", "resources"],
  ["/taxonomy", "resources"],
] as const;

export function NavBar() {
  const pathname = usePathname() ?? "/";
  if (pathname.startsWith("/ask")) return null; // the workspace owns the whole screen
  const current = SECTIONS.find(([prefix]) => pathname.startsWith(prefix))?.[1] ?? "home";
  return <Nav current={current} />;
}
