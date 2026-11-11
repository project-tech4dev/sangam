import type { MeOut } from "@/lib/api";
import { authHeaders } from "@/lib/api/auth-headers";

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

/** A failed call, keeping the status and body so a caller can act on a 409's section. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly body: unknown) {
    super(message);
  }
}

export async function call<T>(path: string, method = "GET", payload?: unknown): Promise<T> {
  const headers = { ...(await authHeaders()), ...(payload === undefined ? {} : { "Content-Type": "application/json" }) };
  const res = await fetch(`${API}${path}`, { method, headers, body: payload === undefined ? undefined : JSON.stringify(payload) });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(body?.detail ?? `Request failed: ${res.status}`, res.status, body);
  return body as T;
}

export const getMe = () => call<MeOut>("/api/me");
