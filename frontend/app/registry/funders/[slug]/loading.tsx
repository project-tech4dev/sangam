// Shown at once on a click, while the server reads the profile; built from existing classes only.
export default function Loading() {
  return (
    <div className="page profile-page">
      <p className="muted ask-pulse" role="status">Loading the profile…</p>
    </div>
  );
}
