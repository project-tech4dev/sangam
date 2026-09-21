const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Funder = {
  id: number;
  slug: string;
  name: string;
  funder_type: string | null;
  website: string | null;
  focus_sectors: string[];
  geographies: string[];
  profile: Record<string, unknown>;
  latest_scores: Record<string, number>;
};

async function getFunders(): Promise<Funder[]> {
  const base = process.env.AGENT_URL ? process.env.AGENT_URL.replace(/\/agent$/, "") : API_URL;
  const res = await fetch(`${base}/api/funders`, {
    headers: { Authorization: "Bearer dev" },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`GET /api/funders failed: ${res.status}`);
  return res.json();
}

export default async function FundersPage() {
  const funders = await getFunders();
  return (
    <div className="page">
      <h1>Funders ({funders.length})</h1>
      <p className="muted">
        KABIL fit scores shown per rubric version (v1 hand-vetted 10 Sep 2026; v2 not yet vetted).
      </p>
      <table className="data">
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Focus</th>
            <th>KABIL fit (v1)</th>
            <th>KABIL fit (v2)</th>
          </tr>
        </thead>
        <tbody>
          {funders.map((funder) => (
            <tr key={funder.id}>
              <td>
                <b>{funder.name}</b>
                {funder.website && (
                  <div className="muted">
                    <a href={funder.website}>{funder.website.replace(/^https?:\/\//, "")}</a>
                  </div>
                )}
              </td>
              <td>{funder.funder_type?.replace(/_/g, " ") ?? "—"}</td>
              <td>
                {funder.focus_sectors.map((s) => (
                  <span key={s} className="pill">
                    {s}
                  </span>
                ))}
              </td>
              <td>{funder.latest_scores?.v1 != null ? `${funder.latest_scores.v1}/100` : "—"}</td>
              <td>{funder.latest_scores?.v2 != null ? `${funder.latest_scores.v2}/100` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
