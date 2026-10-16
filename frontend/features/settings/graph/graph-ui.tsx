import type { ReactNode } from "react";

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
