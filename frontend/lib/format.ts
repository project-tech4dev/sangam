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

/** Rupees as staff say them: ₹4.2 crore, ₹75 lakh, ₹40,000. */
export function formatInr(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  const short = (n: number) => n.toLocaleString("en-IN", { maximumFractionDigits: n < 10 ? 2 : 1 });
  if (abs >= 1e7) return `${sign}₹${short(abs / 1e7)} crore`;
  if (abs >= 1e5) return `${sign}₹${short(abs / 1e5)} lakh`;
  return `${sign}₹${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}
