import { redirect } from "next/navigation";

// Import lives inside the Ask workspace now (sidebar → Tools → Import). The proxy still
// sends a signed-out visitor to sign-in first, with next=/import, which lands here.
export default function ImportPage() {
  redirect("/ask?view=import");
}
