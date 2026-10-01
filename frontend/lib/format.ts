/* Display formatting shared across screens. */

/** Source data arrives SHOUTING from the Darpan portal; mixed case is left alone. */
export function titleCase(value: string | null): string {
  if (!value) return "";
  if (value !== value.toUpperCase()) return value; // already mixed case — leave as-is
  return value
    .toLowerCase()
    .split(/\s+/)
    .map((w) => (w.length > 2 ? w[0]!.toUpperCase() + w.slice(1) : w.toUpperCase()))
    .join(" ");
}

export const ciTypecheckProbe: number = "not a number";
