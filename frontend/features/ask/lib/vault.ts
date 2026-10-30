import { authHeaders } from "@/lib/api/auth-headers";
import { API } from "./rest";

export type Doc = {
  id: number;
  title: string | null;
  doc_type: string | null;
  source_name: string | null;
  source_url: string | null;
  fetched_at: string | null;
  has_file?: boolean;
};

/* Upload in three steps, because the file never passes through the backend:
   ask for a signed URL, PUT straight to Supabase Storage, then tell the
   backend it landed. A Vercel Function caps its request body well below the
   size of an audited-accounts PDF. */
export async function uploadToVault(org: string, file: File): Promise<Doc> {
  const ask = await fetch(`${API}/api/documents/uploads`, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify({ org, filename: file.name }),
  });
  if (ask.status === 503) throw new Error("Document storage is not configured on this deployment.");
  if (ask.status === 403) throw new Error("You do not have upload access to this organisation.");
  if (!ask.ok) throw new Error(`Could not start the upload (${ask.status}).`);
  const { upload_url, storage_path } = await ask.json();

  const put = await fetch(upload_url, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!put.ok) throw new Error(`The file did not reach storage (${put.status}).`);

  const confirm = await fetch(`${API}/api/documents`, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify({ org, storage_path, title: file.name }),
  });
  if (!confirm.ok) throw new Error(`Uploaded, but not recorded (${confirm.status}).`);
  return confirm.json();
}

const DELETE_REFUSED: Record<number, string> = {
  403: "You do not have permission to delete this document.",
  404: "This document is not a Doc Vault upload, or it is already gone.",
  409: "This document is still being used and cannot be deleted.",
};

export async function deleteFromVault(id: number): Promise<void> {
  const res = await fetch(`${API}/api/documents/${id}`, { method: "DELETE", headers: await authHeaders() });
  if (res.ok) return;
  const friendly = DELETE_REFUSED[res.status];
  if (friendly) throw new Error(friendly);
  const detail = await res.json().then((body) => body?.detail, () => null);
  throw new Error(typeof detail === "string" && detail ? detail : "The document could not be deleted. Please try again.");
}

export async function listVault(org: string): Promise<Doc[]> {
  const res = await fetch(`${API}/api/documents?org=${encodeURIComponent(org)}&limit=100`, { headers: await authHeaders() });
  if (!res.ok) throw new Error(`Could not load the Doc Vault (${res.status}).`);
  return (await res.json()).items;
}
