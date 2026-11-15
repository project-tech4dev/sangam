import type { RouteInfo } from "@copilotkit/runtime/v2";

// The runtime also serves its in-memory store of every thread (threads/*, memories/*, inspector/*) to any
// caller. Sangam reads history from the backend's /api/threads, so only what the chat client calls is served.
const SERVED: ReadonlySet<RouteInfo["method"]> = new Set(["info", "agent/run", "agent/connect", "agent/stop", "agent/suggest"]);

/** Throws a 404 Response, which the runtime returns as is, for every route the chat client does not call. */
export function allowRoute(route: RouteInfo): void {
  if (!SERVED.has(route.method)) throw new Response("Not found", { status: 404 });
}
