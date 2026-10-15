import { cookies } from "next/headers";
import { DEV_COOKIE, DEV_LOGIN } from "@/lib/devAuth";
import { createClient } from "@/lib/supabase/server";

export async function serverAuthHeaders(): Promise<Record<string, string>> {
  if (DEV_LOGIN) {
    const email = (await cookies()).get(DEV_COOKIE)?.value;
    return email ? { Authorization: `Bearer dev:${email}` } : {};
  }
  const supabase = await createClient();
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}
