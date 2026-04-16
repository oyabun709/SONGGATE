"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { Bell, Zap, AlertTriangle, Menu } from "lucide-react";
import { cn } from "@/lib/utils";
import { getSubscription, type Subscription } from "@/lib/api";

function UsagePill({ sub }: { sub: Subscription }) {
  const unlimited = sub.scan_limit === -1;
  if (unlimited) return null;

  const pct    = Math.min(100, (sub.scan_count / sub.scan_limit) * 100);
  const warn   = pct >= 70;
  const danger = pct >= 90;

  return (
    <Link
      href="/billing"
      className={cn(
        "flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium transition-colors hover:opacity-80",
        danger
          ? "border-red-200 bg-red-50 text-red-700"
          : warn
          ? "border-amber-200 bg-amber-50 text-amber-700"
          : "border-slate-200 bg-slate-50 text-slate-600"
      )}
    >
      {danger ? (
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
      ) : (
        <Zap className="h-3.5 w-3.5 shrink-0 text-indigo-500" />
      )}
      <span className="tabular-nums">
        {sub.scan_count.toLocaleString()} / {sub.scan_limit.toLocaleString()}
      </span>
      <span className="hidden sm:flex h-1.5 w-14 overflow-hidden rounded-full bg-slate-200">
        <span
          className={cn(
            "h-full rounded-full transition-all",
            danger ? "bg-red-500" : warn ? "bg-amber-400" : "bg-indigo-500"
          )}
          style={{ width: `${pct}%` }}
        />
      </span>
    </Link>
  );
}

interface HeaderProps {
  onMenuClick?: () => void;
}

export function Header({ onMenuClick }: HeaderProps) {
  const { getToken } = useAuth();
  const [sub, setSub] = useState<Subscription | null>(null);

  useEffect(() => {
    getToken().then(async (t) => {
      if (!t) return;
      try { setSub(await getSubscription(t)); } catch { /* not critical */ }
    });
    const id = setInterval(() => {
      getToken().then(async (t) => {
        if (!t) return;
        try { setSub(await getSubscription(t)); } catch { /* */ }
      });
    }, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, [getToken]);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 md:h-16 md:px-6">
      {/* Hamburger — mobile only */}
      <button
        onClick={onMenuClick}
        className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 md:hidden"
        aria-label="Open menu"
      >
        <Menu className="h-5 w-5" />
      </button>

      {/* Spacer on desktop */}
      <div className="hidden md:block" />

      <div className="flex items-center gap-2 md:gap-3">
        {sub && <UsagePill sub={sub} />}
        <button
          className="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          aria-label="Notifications"
        >
          <Bell className="h-5 w-5" />
        </button>
      </div>
    </header>
  );
}
