import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import * as React from "react";

// Mutable so a test can set the path or query the component reads.
export const navigation = {
  pathname: "/",
  search: new URLSearchParams(),
  router: { push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
};

vi.mock("next/navigation", () => ({
  useRouter: () => navigation.router,
  usePathname: () => navigation.pathname,
  useSearchParams: () => navigation.search,
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}));

type LinkProps = { href: string | { pathname?: string }; children?: React.ReactNode } & Record<string, unknown>;

vi.mock("next/link", () => ({
  default: function Link({ href, children, ...rest }: LinkProps) {
    delete rest.prefetch;
    return React.createElement("a", { href: typeof href === "string" ? href : href.pathname, ...rest }, children);
  },
}));

// jsdom has no IntersectionObserver; tests that need it to fire replace this stub.
class NoopIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() { return []; }
}
// Assigned, not stubbed, so a test's vi.unstubAllGlobals() cannot take it away.
globalThis.IntersectionObserver ??= NoopIntersectionObserver as unknown as typeof IntersectionObserver;

afterEach(() => {
  cleanup();
  navigation.pathname = "/";
  navigation.search = new URLSearchParams();
  Object.values(navigation.router).forEach((f) => f.mockReset());
});
