import { redirect } from "next/navigation";

export default function FundersRedirect() {
  redirect("/registry?type=funder");
}
