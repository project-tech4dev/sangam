// Shown at once on a click, while the server reads the first page; built from existing classes only.
export default function Loading() {
  return (
    <div className="page">
      <p className="muted ask-pulse" role="status">Loading the Registry…</p>
    </div>
  );
}
