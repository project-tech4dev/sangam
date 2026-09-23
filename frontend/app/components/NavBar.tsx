"use client";

import { usePathname } from "next/navigation";
import { Nav } from "./Nav";

export function NavBar() {
  const pathname = usePathname() ?? "/";
  const current = pathname.startsWith("/ask")
    ? "ask"
    : pathname.startsWith("/registry") || pathname.startsWith("/orgs") || pathname.startsWith("/funders")
      ? "registry"
      : pathname.startsWith("/resources") || pathname.startsWith("/methodology") || pathname.startsWith("/taxonomy")
        ? "resources"
        : "home";
  return <Nav current={current} />;
}
