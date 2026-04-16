"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  RefreshCw,
  Activity,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { listOrgScans, type ScanWithRelease } from "@/lib/api";

function StatusIcon({ status }: { status: string }) {
  if (status === "complete") return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-red-500" />;
  if (status === "running") return <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />;
  return <Clock className="h-4 w-4 text-slate-400" />;
}

function GradeBadge({ grade }: { grade: string | null }) {
  if (!grade) return <span className="text-xs text-slate-400">—</span>;
  const cls: Record<string, string> = {
    PASS: "bg-emerald-100 text-emerald-700",
    WARN: "bg-amber-100 text-amber-700",
    FAIL: "bg-red-100 text-red-700",
  };
  return (
    <span className={cn("inline-flex rounded-full px-2 py-0.5 text-xs font-semibold", cls[grade] ?? "bg-slate-100 text-slate-500")}>
      {grade}
    </span>
  );
}

function duration(scan: ScanWithRelease): string {
  if (!scan.started_at || !scan.completed_at) return "—";
  const ms = new Date(scan.completed_at).getTime() - new Date(scan.started_at).getTime();
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function PipelinesPage() {
  const { getToken } = useAuth();
  const [scans, setScans] = useState<ScanWithRelease[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const token = await getToken();
      if (!token) return;
      setScans(await listOrgScans(token, 50));
    } catch {
      /* empty state */
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const active = scans.filter((s) => s.status === "running" || s.status === "queued");
  const finished = scans.filter((s) => s.status === "complete" || s.status === "failed");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Pipelines</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            All QA pipeline runs across your releases.
          </p>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>

      {/* Active runs */}
      {active.length > 0 && (
        <div className="rounded-lg border border-indigo-200 bg-indigo-50/40 p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-indigo-600">
            Active ({active.length})
          </p>
          <div className="space-y-2">
            {active.map((scan) => (
              <div key={scan.id} className="flex items-center justify-between rounded-md border border-indigo-100 bg-white px-4 py-3">
                <div className="flex items-center gap-3">
                  <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />
                  <div>
                    <p className="text-sm font-medium text-slate-800">{scan.release_title}</p>
                    <p className="text-xs text-slate-400">{scan.release_artist} · {scan.status}</p>
                  </div>
                </div>
                <span className="text-xs text-slate-400">
                  {new Date(scan.created_at).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* History */}
      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 className="text-sm font-semibold text-slate-900">Run History</h2>
          <span className="text-xs text-slate-400">{scans.length} total</span>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
          </div>
        ) : scans.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Activity className="mb-3 h-8 w-8 text-slate-300" />
            <p className="text-sm font-medium text-slate-500">No pipeline runs yet</p>
            <p className="mt-0.5 text-xs text-slate-400">Runs appear here as soon as you submit a scan.</p>
            <Link
              href="/releases/new"
              className="mt-4 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
            >
              New Scan
            </Link>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left">
                  {["Status", "Release", "Score", "Grade", "Issues", "Duration", "Date", ""].map((h) => (
                    <th key={h} className="px-5 py-3 text-xs font-medium uppercase tracking-wider text-slate-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {scans.map((scan) => (
                  <tr key={scan.id} className="hover:bg-slate-50/60">
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-1.5">
                        <StatusIcon status={scan.status} />
                        <span className="capitalize text-xs text-slate-500">{scan.status}</span>
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      <p className="text-sm font-medium text-slate-800 truncate max-w-[160px]">{scan.release_title}</p>
                      <p className="text-xs text-slate-400 truncate max-w-[160px]">{scan.release_artist}</p>
                    </td>
                    <td className="px-5 py-3.5 tabular-nums text-xs font-semibold text-slate-700">
                      {scan.readiness_score != null ? Math.round(scan.readiness_score) : "—"}
                    </td>
                    <td className="px-5 py-3.5"><GradeBadge grade={scan.grade} /></td>
                    <td className="px-5 py-3.5 text-xs text-slate-500 tabular-nums">
                      <span className="text-red-600 font-medium">{scan.critical_count}</span>
                      <span className="text-slate-300 mx-1">/</span>
                      <span className="text-amber-600">{scan.warning_count}</span>
                      <span className="text-slate-300 mx-1">/</span>
                      <span className="text-slate-400">{scan.info_count}</span>
                    </td>
                    <td className="px-5 py-3.5 text-xs text-slate-400 tabular-nums">{duration(scan)}</td>
                    <td className="px-5 py-3.5 text-xs text-slate-400">
                      {new Date(scan.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      {scan.status === "complete" && (
                        <Link href={`/scans/${scan.id}`} className="text-xs font-medium text-indigo-600 hover:text-indigo-700">
                          View →
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
