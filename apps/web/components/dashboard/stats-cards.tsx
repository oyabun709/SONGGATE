"use client";

import { Package, CheckCircle2, XCircle, Clock } from "lucide-react";

const stats = [
  {
    label: "Total Releases",
    value: "—",
    icon: Package,
    color: "text-indigo-600",
    bg: "bg-indigo-50",
  },
  {
    label: "Passed",
    value: "—",
    icon: CheckCircle2,
    color: "text-emerald-600",
    bg: "bg-emerald-50",
  },
  {
    label: "Failed",
    value: "—",
    icon: XCircle,
    color: "text-red-600",
    bg: "bg-red-50",
  },
  {
    label: "In Progress",
    value: "—",
    icon: Clock,
    color: "text-amber-600",
    bg: "bg-amber-50",
  },
];

export function StatsCards() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {stats.map((stat) => (
        <div
          key={stat.label}
          className="rounded-lg border border-slate-200 bg-white p-5"
        >
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-slate-500">{stat.label}</p>
            <span className={`rounded-md p-1.5 ${stat.bg}`}>
              <stat.icon className={`h-4 w-4 ${stat.color}`} />
            </span>
          </div>
          <p className="mt-3 text-2xl font-semibold text-slate-900">
            {stat.value}
          </p>
        </div>
      ))}
    </div>
  );
}
