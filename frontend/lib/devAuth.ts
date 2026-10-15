// Local testing only: with no Supabase keys and NEXT_PUBLIC_DEV_AUTH=1, sign in as a seeded @local.test user.
export const DEV_LOGIN = !process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_DEV_AUTH === "1";
export const DEV_COOKIE = "sangam-dev-as";
export const DEV_USERS = ["admin", "steward", "member", "stranger"].map((r) => `${r}@local.test`);

export function devEmail(): string | null {
  if (!DEV_LOGIN || typeof document === "undefined") return null;
  const hit = document.cookie.split("; ").find((c) => c.startsWith(`${DEV_COOKIE}=`));
  return hit ? decodeURIComponent(hit.slice(DEV_COOKIE.length + 1)) : null;
}

export function setDevEmail(email: string | null) {
  document.cookie = email
    ? `${DEV_COOKIE}=${encodeURIComponent(email)}; path=/; SameSite=Lax`
    : `${DEV_COOKIE}=; path=/; max-age=0`;
}
