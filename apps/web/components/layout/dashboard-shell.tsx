"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { useOrganization } from "@clerk/nextjs";
import Link from "next/link";
import { Sidebar } from "./sidebar";
import { Header } from "./header";
import { cn } from "@/lib/utils";

export function DashboardShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const { organization } = useOrganization();

  // Detect demo org by clerk_org_id or org name
  const isDemo =
    organization?.slug === "songgate-demo" ||
    organization?.name === "SONGGATE Demo" ||
    organization?.id === "org_demo_songgate_2026";

  // Close drawer on route change
  useEffect(() => { setOpen(false); }, [pathname]);

  // Prevent body scroll when drawer is open
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-slate-50">
      {/* Demo environment banner */}
      {isDemo && (
        <div className="shrink-0 bg-indigo-600 py-1.5 text-center text-xs font-semibold text-white z-50">
          Demo Environment —{" "}
          <Link href="/sign-up" className="underline hover:text-indigo-200">
            Book a pilot at songgate.io
          </Link>
        </div>
      )}
    <div className="flex flex-1 min-h-0 overflow-hidden">
      {/* Mobile backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-20 bg-black/40 md:hidden"
          onClick={() => setOpen(false)}
        />
      )}

      {/* Sidebar — drawer on mobile, fixed on desktop */}
      <div
        className={cn(
          "fixed inset-y-0 left-0 z-30 transition-transform duration-200 ease-in-out",
          "md:relative md:z-auto md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        )}
      >
        <Sidebar onClose={() => setOpen(false)} />
      </div>

      {/* Main content */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Header onMenuClick={() => setOpen((o) => !o)} />
        <main className="flex-1 overflow-y-auto p-4 md:p-6">{children}</main>
      </div>
    </div>
    </div>
  );
}
