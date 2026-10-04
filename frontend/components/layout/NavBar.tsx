"use client";

import { usePathname } from "next/navigation";
import { Nav } from "./Nav";

// First prefix that matches wins, so /orgs and /funders read as Registry.
const SECTIONS = [
  ["/ask", "ask"],
  ["/registry", "registry"],
  ["/orgs", "registry"],
  ["/funders", "registry"],
  ["/resources", "resources"],
  ["/methodology", "resources"],
  ["/taxonomy", "resources"],
] as const;

export function NavBar() {
  const pathname = usePathname() ?? "/";
  const current = SECTIONS.find(([prefix]) => pathname.startsWith(prefix))?.[1] ?? "home";
  return <Nav current={current} />;
}
