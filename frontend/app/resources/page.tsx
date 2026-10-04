import { redirect } from "next/navigation";

// Resources opens on its first tab.
export default function Resources() {
  redirect("/resources/methodology");
}
