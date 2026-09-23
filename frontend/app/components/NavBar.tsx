"use client";

import { usePathname } from "next/navigation";
import { Nav } from "./Nav";

export function NavBar() {
  const pathname = usePathname() ?? "/";
  if (pathname.startsWith("/ask")) return null; // the workspace owns the whole screen
  const current = pathname.startsWith("/ask")
    ? "ask"
    : pathname.startsWith("/registry") || pathname.startsWith("/orgs") || pathname.startsWith("/funders")
      ? "registry"
      : pathname.startsWith("/resources") || pathname.startsWith("/methodology") || pathname.startsWith("/taxonomy")
        ? "resources"
        : "home";
  return <Nav current={current} />;
}
