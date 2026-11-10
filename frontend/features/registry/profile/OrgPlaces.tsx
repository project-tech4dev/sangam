import type { Place, ProgramNode } from "@/lib/api";
import { titleCase } from "@/lib/format";
import { Card, Empty, ProgramTree, SourceLink } from "./shared";

/* Where the organisation works, states first, with the districts under each. */
export function placeGroups(places: Place[]) {
  const worked = places.filter((p) => p.role !== "registered");
  const groups = new Map<string, { districts: Place[]; stateRows: Place[] }>();
  for (const p of worked) {
    const state = p.state ?? p.name;
    const g = groups.get(state) ?? { districts: [], stateRows: [] };
    if (p.kind === "state") g.stateRows.push(p);
    else g.districts.push(p);
    groups.set(state, g);
  }
  const sorted = [...groups.entries()].sort((a, b) => b[1].districts.length - a[1].districts.length);
  const districts = new Set(worked.filter((p) => p.kind === "district").map((p) => p.location_id)).size;
  return { groups: sorted, districts, states: sorted.length };
}

export function OrgPlaces({ places, programs }: { places: Place[]; programs: ProgramNode[] }) {
  const { groups, districts, states } = placeGroups(places);
  const office = places.find((p) => p.role === "registered");

  return (
    <div className="profile-tab">
      <Card kicker="Where it works">
        <div className="profile-stats">
          <div><div className="profile-statn">{districts}</div><div className="profile-kicker">Districts</div></div>
          <div><div className="profile-statn">{states}</div><div className="profile-kicker">States</div></div>
          {office && (
            <div>
              <div className="profile-statn">1</div>
              <div className="profile-kicker">Registered office · {titleCase(office.name)}</div>
            </div>
          )}
        </div>
        {groups.length === 0 ? <Empty>No places recorded yet.</Empty> : (
          <div className="profile-grid">
            {groups.map(([state, g]) => (
              <div key={state} className="profile-line">
                <strong>{state}</strong>
                {g.districts.length === 0 && (
                  <span className="muted profile-sm">
                    State only, no district named.{g.stateRows[0]?.note ? ` ${g.stateRows[0].note}` : ""}
                  </span>
                )}
                {g.districts.map((d) => (
                  <div key={d.location_id} className="profile-place">
                    <div className="profile-row">
                      <span>{titleCase(d.name)}</span>
                      <SourceLink url={d.source_url} />
                    </div>
                    {(d.note || d.program_name) && (
                      <span className="profile-note">{[d.program_name, d.note].filter(Boolean).join(" · ")}</span>
                    )}
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card kicker={`Programmes · ${programs.length}`}>
        <ProgramTree programs={programs} />
      </Card>
    </div>
  );
}
