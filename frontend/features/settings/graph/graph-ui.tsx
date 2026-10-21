import type { ReactNode } from "react";
import { ENTITY_TYPES, type GraphEntity } from "./graph-api";

export const inputClass = "h-8 rounded-full border border-neutral-300 bg-white px-3 text-sm";
export const GROUP_HINT = "Letters, digits, - and _ only";

export function Card({ title, note, children }: { title: string; note: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4 rounded-lg border border-neutral-300 bg-white p-5">
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="text-sm text-neutral-600">{note}</p>
      </div>
      {children}
    </section>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-neutral-600">{label}</span>
      {children}
    </label>
  );
}

export function Pills({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="text-sm text-neutral-500">None</p>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((item, i) => (
        <li key={`${item}-${i}`} className="rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs">
          {item}
        </li>
      ))}
    </ul>
  );
}

export function FactList({ facts }: { facts: string[] }) {
  if (facts.length === 0) return <p className="text-sm text-neutral-500">None</p>;
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {facts.map((fact, i) => (
        <li key={i}>{fact}</li>
      ))}
    </ul>
  );
}

export function ErrorText({ error }: { error: string | null }) {
  return error ? <p className="text-sm text-terracotta-750">{error}</p> : null;
}

export function EntitiesByType({ entities }: { entities: GraphEntity[] }) {
  if (entities.length === 0) return <p className="text-sm text-neutral-500">None</p>;
  const types = [...ENTITY_TYPES, ...new Set(entities.map((e) => e.type))].filter(
    (type, i, all) => all.indexOf(type) === i && entities.some((e) => e.type === type),
  );
  return (
    <dl className="flex flex-col gap-2">
      {types.map((type) => {
        const ofType = entities.filter((e) => e.type === type);
        return (
          <div key={type} className="flex flex-col gap-1">
            <dt className="text-xs text-neutral-600">
              {type} ({ofType.length})
            </dt>
            <dd>
              <Pills items={ofType.map((e) => (e.sangam_id ? `${e.name} ✓ ${e.sangam_id}` : e.name))} />
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

export function DroppedFacts({ facts }: { facts: string[] }) {
  if (facts.length === 0) return null;
  return (
    <details className="text-sm text-neutral-600">
      <summary className="cursor-pointer">{facts.length} facts dropped: outside the ontology</summary>
      <FactList facts={facts} />
    </details>
  );
}

export function UnmappedThemes({ names }: { names: string[] }) {
  if (names.length === 0) return null;
  return (
    <details className="text-sm text-neutral-600">
      <summary className="cursor-pointer">{names.length} not in the taxonomy, labelled Unmapped</summary>
      <Pills items={names} />
    </details>
  );
}

export function ExtractionResult({
  entities,
  facts,
  dropped,
  unmapped = [],
  small = false,
}: {
  entities: GraphEntity[];
  facts: string[];
  dropped: string[];
  unmapped?: string[];
  small?: boolean;
}) {
  const heading = small ? "text-xs font-semibold text-neutral-600" : "text-sm font-semibold";
  const linked = entities.filter((e) => e.sangam_id).length;
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <h4 className={heading}>
            Entities ({entities.length}, {linked} linked to Sangam)
          </h4>
          <EntitiesByType entities={entities} />
        </div>
        <div className="flex flex-col gap-2">
          <h4 className={heading}>Facts kept ({facts.length})</h4>
          <FactList facts={facts} />
        </div>
      </div>
      <DroppedFacts facts={dropped} />
      <UnmappedThemes names={unmapped} />
    </div>
  );
}
