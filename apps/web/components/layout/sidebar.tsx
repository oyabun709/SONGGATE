"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserButton, useOrganization, useUser } from "@clerk/nextjs";
import {
  LayoutDashboard,
  Package,
  GitBranch,
  ShieldCheck,
  BarChart3,
  TrendingUp,
  CreditCard,
  Settings,
  Zap,
  Building2,
  ShieldAlert,
  X,
  Database,
} from "lucide-react";
import { cn } from "@/lib/utils";

const ADMIN_IDS = (process.env.NEXT_PUBLIC_ADMIN_CLERK_IDS ?? "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

const navItems = [
  { href: "/dashboard",  label: "Dashboard",  icon: LayoutDashboard },
  { href: "/releases",   label: "Releases",   icon: Package },
  { href: "/pipelines",  label: "Pipelines",  icon: GitBranch },
  { href: "/rules",      label: "Rules",      icon: ShieldCheck },
  { href: "/catalog",    label: "Catalog",    icon: Database,   badge: "Index" },
  { href: "/analytics",  label: "Analytics",  icon: TrendingUp, badge: "Corpus" },
  { href: "/reports",    label: "Reports",    icon: BarChart3 },
  { href: "/billing",    label: "Billing",    icon: CreditCard },
];

interface SidebarProps {
  onClose?: () => void;
}

export function Sidebar({ onClose }: SidebarProps) {
  const pathname  = usePathname();
  const { organization } = useOrganization();
  const { user }  = useUser();
  const isAdmin   = !!user && ADMIN_IDS.includes(user.id);

  return (
    <aside className="flex h-full w-64 flex-col border-r border-slate-200 bg-white md:w-60">
      {/* Logo + mobile close */}
      <div className="flex h-14 items-center justify-between border-b border-slate-200 px-5 md:h-16">
        <div className="flex items-center gap-2">
          <Zap className="h-5 w-5 text-indigo-600" />
          <span className="text-lg font-semibold tracking-tight text-slate-900">
            SONGGATE
          </span>
        </div>
        <button
          onClick={onClose}
          className="rounded-md p-1 text-slate-400 hover:bg-slate-100 md:hidden"
          aria-label="Close menu"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* Org badge */}
      {organization && (
        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
          <Building2 className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          <span className="truncate text-xs font-medium text-slate-600">
            {organization.name}
          </span>
        </div>
      )}

      {/* Nav */}
      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2">
        {navItems.map(({ href, label, icon: Icon, badge }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
              pathname === href || pathname.startsWith(href + "/")
                ? "bg-indigo-50 text-indigo-700"
                : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span className="flex-1">{label}</span>
            {badge && (
              <span className="rounded-full bg-indigo-100 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-600 leading-none">
                {badge}
              </span>
            )}
          </Link>
        ))}
      </nav>

      {/* Footer */}
      <div className="space-y-0.5 border-t border-slate-200 p-2">
        {isAdmin && (
          <Link
            href="/admin"
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
              pathname === "/admin" || pathname.startsWith("/admin/")
                ? "bg-red-50 text-red-700"
                : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
            )}
          >
            <ShieldAlert className="h-4 w-4 shrink-0" />
            <span className="flex-1">Admin</span>
            <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold text-red-600 leading-none">
              DEV
            </span>
          </Link>
        )}

        <Link
          href="/settings"
          className="flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-900"
        >
          <Settings className="h-4 w-4 shrink-0" />
          Settings
        </Link>

        <div className="flex items-center gap-3 rounded-md px-3 py-2">
          <UserButton
            afterSignOutUrl="/sign-in"
            appearance={{ elements: { avatarBox: "h-7 w-7" } }}
          />
          <span className="text-sm text-slate-600">Account</span>
        </div>
      </div>
    </aside>
  );
}
