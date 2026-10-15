import { createClient } from "@/lib/supabase/client";
import { DEV_LOGIN, devEmail } from "@/lib/devAuth";

export async function authHeaders(): Promise<Record<string, string>> {
  if (DEV_LOGIN) {
    const email = devEmail();
    return email ? { Authorization: `Bearer dev:${email}` } : {};
  }
  const { data } = await createClient().auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}
