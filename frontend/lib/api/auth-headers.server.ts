import { createClient } from "@/lib/supabase/server";

export async function serverAuthHeaders(): Promise<Record<string, string>> {
  const supabase = await createClient();
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}
