const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Org = {
  id: number;
  slug: string;
  name: string;
  darpan_id: string | null;
  cohort: string | null;
  state: string | null;
  district: string | null;
  sectors: string[];
  source_name: string | null;
  fetched_at: string | null;
};

async function getOrgs(): Promise<Org[]> {
  // Server component: inside docker this fetch runs in the frontend container,
  // so use the internal backend URL when provided.
  const base = process.env.AGENT_URL ? process.env.AGENT_URL.replace(/\/agent$/, "") : API_URL;
  const res = await fetch(`${base}/api/orgs`, {
    headers: { Authorization: "Bearer dev" },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`GET /api/orgs failed: ${res.status}`);
  return res.json();
}

export default async function OrgsPage() {
  const orgs = await getOrgs();
  return (
    <div className="page">
      <h1>Organisations ({orgs.length})</h1>
      <table className="data">
        <thead>
          <tr>
            <th>Name</th>
            <th>Darpan ID</th>
            <th>Location</th>
            <th>Sectors</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {orgs.map((org) => (
            <tr key={org.id}>
              <td>
                <b>{org.name}</b>
                <div className="muted">{org.slug}</div>
              </td>
              <td>{org.darpan_id ?? "—"}</td>
              <td>
                {[org.district, org.state].filter(Boolean).join(", ") || "—"}
              </td>
              <td>
                {org.sectors.map((s) => (
                  <span key={s} className="pill">
                    {s}
                  </span>
                ))}
              </td>
              <td className="muted">{org.source_name ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
