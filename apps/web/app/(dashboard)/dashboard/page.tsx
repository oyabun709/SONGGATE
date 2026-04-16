"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import {
  Package,
  CheckCircle2,
  XCircle,
  TrendingUp,
  ArrowRight,
  RefreshCw,
  Plus,
} from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { cn } from "@/lib/utils";
import {
  listReleases,
  getDashboardStats,
  type Release,
  type DashboardStats,
} from "@/lib/api";

function GradeBadge({ grade }: { grade: string | null }) {
  if (!grade) return <span className="text-xs text-slate-400">—</span>;
  const cls = {
    PASS: "bg-emerald-100 text-emerald-700",
    WARN: "bg-amber-100 text-amber-700",
    FAIL: "bg-red-100 text-red-700",
  }[grade] ?? "bg-slate-100 text-slate-500";
  return (
    <span className={cn("inline-flex rounded-full px-2 py-0.5 text-xs font-semibold", cls)}>
      {grade}
    </span>
  );
}

const LAYER_COLORS: Record<string, string> = {
  artwork: "bg-pink-400",
  metadata: "bg-blue-400",
  audio: "bg-amber-400",
  fraud: "bg-red-400",
  ddex: "bg-violet-400",
  enrichment: "bg-emerald-400",
};

const SEVERITY_CLS: Record<string, string> = {
  critical: "bg-red-100 text-red-700",
  warning: "bg-amber-100 text-amber-700",
  info: "bg-blue-50 text-blue-700",
};

function ruleLabel(rule_id: string): string {
  // "universal.artwork.resolution_too_low" → "Resolution Too Low"
  const parts = rule_id.split(".");
  return parts.slice(2).join(" ").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) || rule_id;
}

export default function DashboardPage() {
  const { getToken } = useAuth();
  const [releases, setReleases] = useState<Release[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const token = await getToken();
      if (!token) return;
      const [rel, st] = await Promise.all([
        listReleases(token),
        getDashboardStats(token),
      ]);
      setReleases(rel);
      setStats(st);
    } catch {
      /* show empty state */
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const total = releases.length;
  const passRate =
    total > 0
      ? Math.round((releases.filter((r) => r.latest_scan_grade === "PASS").length / total) * 100)
      : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Release QA overview — all active scans and issues.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchData}
            className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
          <Link
            href="/releases/new"
            className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-indigo-700"
          >
            <Plus className="h-3.5 w-3.5" />
            New Scan
          </Link>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[
          {
            label: "Total Releases Scanned",
            value: loading ? "…" : String(total),
            icon: Package,
            color: "text-indigo-600",
            bg: "bg-indigo-50",
          },
          {
            label: "PASS Rate",
            value: loading ? "…" : passRate !== null ? `${passRate}%` : "—",
            icon: CheckCircle2,
            color: "text-emerald-600",
            bg: "bg-emerald-50",
          },
          {
            label: "Critical Issues",
            value: loading ? "…" : stats ? String(stats.critical_issues) : "—",
            icon: XCircle,
            color: "text-red-600",
            bg: "bg-red-50",
          },
          {
            label: "Scans This Month",
            value: loading ? "…" : stats ? String(stats.scans_this_month) : "—",
            icon: TrendingUp,
            color: "text-violet-600",
            bg: "bg-violet-50",
          },
        ].map((s) => (
          <div key={s.label} className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium uppercase tracking-wider text-slate-400">{s.label}</p>
              <span className={cn("rounded-md p-1.5", s.bg)}>
                <s.icon className={cn("h-4 w-4", s.color)} />
              </span>
            </div>
            <p className="mt-3 text-2xl font-bold text-slate-900">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Main grid: recent scans + top issues */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        {/* Recent Scans table — 2/3 */}
        <div className="xl:col-span-2 rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <h2 className="text-sm font-semibold text-slate-900">Recent Scans</h2>
            <Link href="/releases" className="flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-700">
              View all <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
            </div>
          ) : releases.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Package className="mb-3 h-8 w-8 text-slate-300" />
              <p className="text-sm font-medium text-slate-500">No releases yet</p>
              <p className="mt-0.5 text-xs text-slate-400">Upload a DDEX package to run your first scan.</p>
              <Link href="/releases/new" className="mt-4 flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700">
                <Plus className="h-3.5 w-3.5" />New Scan
              </Link>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left">
                    {["Release", "Artist", "Score", "Grade", "Date", ""].map((h) => (
                      <th key={h} className="px-5 py-3 text-xs font-medium uppercase tracking-wider text-slate-400">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {releases.slice(0, 8).map((r) => (
                    <tr key={r.id} className="hover:bg-slate-50/60">
                      <td className="px-5 py-3 font-medium text-slate-800">{r.title}</td>
                      <td className="px-5 py-3 text-slate-500">{r.artist}</td>
                      <td className="px-5 py-3">
                        {r.latest_scan_score != null
                          ? <span className="tabular-nums text-xs font-semibold text-slate-700">{Math.round(r.latest_scan_score)}</span>
                          : <span className="text-xs text-slate-400">—</span>}
                      </td>
                      <td className="px-5 py-3"><GradeBadge grade={r.latest_scan_grade ?? null} /></td>
                      <td className="px-5 py-3 text-xs text-slate-400">{new Date(r.created_at).toLocaleDateString()}</td>
                      <td className="px-5 py-3 text-right">
                        {r.latest_scan_id
                          ? <Link href={`/scans/${r.latest_scan_id}`} className="text-xs font-medium text-indigo-600 hover:text-indigo-700">View Scan →</Link>
                          : <Link href={`/releases/${r.id}`} className="text-xs font-medium text-slate-400 hover:text-slate-600">Details →</Link>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Top Issues */}
        <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 px-5 py-4">
            <h2 className="text-sm font-semibold text-slate-900">Top Issues</h2>
            <p className="mt-0.5 text-xs text-slate-400">Most frequent failures across all scans</p>
          </div>
          {loading ? (
            <div className="flex items-center justify-center py-10">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
            </div>
          ) : !stats || stats.top_issues.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-center px-5">
              <CheckCircle2 className="mb-2 h-7 w-7 text-slate-200" />
              <p className="text-sm text-slate-400">No issues found yet</p>
              <p className="mt-0.5 text-xs text-slate-300">Run a scan to see top issues here.</p>
            </div>
          ) : (
            <div className="divide-y divide-slate-50">
              {stats.top_issues.map((issue, i) => (
                <div key={issue.rule_id} className="flex items-start gap-3 px-5 py-3.5">
                  <span className="mt-0.5 w-4 text-xs font-bold text-slate-300 tabular-nums">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-slate-700">
                      {ruleLabel(issue.rule_id)}
                    </p>
                    <div className="mt-1 flex items-center gap-2">
                      <span className={cn("inline-block h-2 w-2 rounded-full", LAYER_COLORS[issue.layer] ?? "bg-slate-300")} />
                      <span className="text-xs capitalize text-slate-400">{issue.layer}</span>
                      <span className={cn("rounded px-1.5 py-0.5 text-xs font-medium capitalize", SEVERITY_CLS[issue.severity] ?? "bg-slate-100 text-slate-500")}>
                        {issue.severity}
                      </span>
                    </div>
                  </div>
                  <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600 tabular-nums">
                    {issue.count}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Issue trend chart */}
      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Issue Trend — Last 30 Days</h2>
            <p className="mt-0.5 text-xs text-slate-400">Critical · Warning · Info counts per day</p>
          </div>
        </div>
        {loading ? (
          <div className="flex items-center justify-center" style={{ height: 196 }}>
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
          </div>
        ) : !stats || stats.trend.every((p) => p.critical === 0 && p.warning === 0 && p.info === 0) ? (
          <div className="flex flex-col items-center justify-center text-center" style={{ height: 196 }}>
            <TrendingUp className="mb-2 h-7 w-7 text-slate-200" />
            <p className="text-sm text-slate-400">No scan data in the last 30 days</p>
            <p className="mt-0.5 text-xs text-slate-300">Trend will appear after your first scan.</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={196}>
            <AreaChart data={stats.trend} margin={{ top: 0, right: 4, left: -20, bottom: 0 }}>
              <defs>
                {[
                  { id: "gCritical", color: "#ef4444" },
                  { id: "gWarning", color: "#f59e0b" },
                  { id: "gInfo", color: "#6366f1" },
                ].map(({ id, color }) => (
                  <linearGradient key={id} id={id} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={color} stopOpacity={0.15} />
                    <stop offset="95%" stopColor={color} stopOpacity={0} />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval={6} />
              <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip
                contentStyle={{ backgroundColor: "#1e293b", border: "none", borderRadius: "6px", fontSize: "12px", color: "#f1f5f9" }}
                itemStyle={{ color: "#f1f5f9" }}
                labelStyle={{ color: "#94a3b8", marginBottom: "4px" }}
              />
              <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: "12px", paddingTop: "8px" }} />
              <Area type="monotone" dataKey="critical" stroke="#ef4444" strokeWidth={2} fill="url(#gCritical)" name="Critical" />
              <Area type="monotone" dataKey="warning" stroke="#f59e0b" strokeWidth={2} fill="url(#gWarning)" name="Warning" />
              <Area type="monotone" dataKey="info" stroke="#6366f1" strokeWidth={1.5} fill="url(#gInfo)" name="Info" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
