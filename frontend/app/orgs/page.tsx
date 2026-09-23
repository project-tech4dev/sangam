import { redirect } from "next/navigation";

export default function OrgsRedirect() {
  redirect("/registry?type=cso");
}
