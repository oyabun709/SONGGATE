import { redirect } from "next/navigation";

// /share with no token — redirect to homepage
export default function ShareIndexPage() {
  redirect("/");
}
