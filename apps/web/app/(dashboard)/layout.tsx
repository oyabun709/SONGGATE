import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { OrgActivator } from "@/components/auth/org-activator";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { userId } = await auth();
  if (!userId) redirect("/sign-in");

  return (
    <>
      <OrgActivator />
      <DashboardShell>{children}</DashboardShell>
    </>
  );
}
