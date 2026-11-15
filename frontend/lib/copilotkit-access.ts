import type { RouteInfo } from "@copilotkit/runtime/v2";

// The runtime also serves its in-memory store of every thread (threads/*, memories/*, inspector/*) to any
// caller. Sangam reads history from the backend's /api/threads, so only what the chat client calls is served.
const SERVED: ReadonlySet<RouteInfo["method"]> = new Set(["info", "agent/run", "agent/connect", "agent/stop", "agent/suggest"]);

/** Throws a 404 Response, which the runtime returns as is, for every route the chat client does not call. */
export function allowRoute(route: RouteInfo): void {
  if (!SERVED.has(route.method)) throw new Response("Not found", { status: 404 });
}

/** The backend's status for "may this caller post in this thread": 204 yes, 401 signed out, 404 no. */
export type OwnerCheck = (threadId: string, authorization: string) => Promise<number>;

export function backendOwnerCheck(apiBase: string, fetchImpl?: typeof fetch): OwnerCheck {
  return async (threadId, authorization) => {
    const res = await (fetchImpl ?? fetch)(`${apiBase}/api/threads/${encodeURIComponent(threadId)}/owned`, {
      headers: { Authorization: authorization },
      cache: "no-store",
    });
    return res.status;
  };
}

async function connectThreadId(request: Request): Promise<string | null> {
  try {
    // A clone: the runtime reads the body again after this hook.
    const body: unknown = await request.clone().json();
    const threadId = (body as { threadId?: unknown } | null)?.threadId;
    return typeof threadId === "string" && threadId ? threadId : null;
  } catch {
    return null;
  }
}

/**
 * The route allowlist, then the owner rule for connect and stop: they replay or stop a run in this instance's
 * memory by thread id alone, so only the thread's owner (or anyone, before a turn has claimed it) gets through.
 */
export async function gateRoute(
  route: RouteInfo,
  request: Request,
  authorization: () => Promise<string | undefined>,
  isOwner: OwnerCheck,
): Promise<void> {
  allowRoute(route);
  if (route.method !== "agent/connect" && route.method !== "agent/stop") return;
  const threadId = route.method === "agent/stop" ? route.threadId : await connectThreadId(request);
  if (!threadId) throw new Response("Bad request", { status: 400 });
  const auth = await authorization();
  if (!auth) throw new Response("Sign in required", { status: 401 });
  let status: number;
  try {
    status = await isOwner(threadId, auth);
  } catch {
    throw new Response("Thread not found", { status: 404 });
  }
  if (status === 401) throw new Response("Sign in required", { status: 401 });
  if (status < 200 || status >= 300) throw new Response("Thread not found", { status: 404 });
}
