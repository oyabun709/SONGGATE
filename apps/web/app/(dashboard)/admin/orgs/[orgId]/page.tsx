"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { ArrowLeft, RefreshCw, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { adminListOrgScans, type AdminScanItem } from "@/lib/api";

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

function StatusDot({ status }: { status: string }) {
  const cls: Record<string, string> = {
    complete: "bg-emerald-400",
    running: "bg-blue-400 animate-pulse",
    queued: "bg-slate-300",
    failed: "bg-red-400",
  };
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn("inline-block h-2 w-2 rounded-full", cls[status] ?? "bg-slate-300")} />
      <span className="capitalize text-xs text-slate-600">{status}</span>
    </span>
  );
}

export default function AdminOrgDetailPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const { getToken } = useAuth();
  const [scans, setScans] = useState<AdminScanItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchScans = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      if (!token) return;
      setScans(await adminListOrgScans(orgId, token));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load scans");
    } finally {
      setLoading(false);
    }
  }, [orgId, getToken]);

  useEffect(() => { fetchScans(); }, [fetchScans]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            href="/admin"
            className="flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-800"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            All Orgs
          </Link>
          <span className="text-slate-300">/</span>
          <h1 className="text-lg font-semibold text-slate-900">Org Scans</h1>
          <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-500">{orgId}</span>
        </div>
        <button
          onClick={fetchScans}
          className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
          </div>
        ) : scans.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <p className="text-sm text-slate-500">No scans for this org yet</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left">
                  {["Release", "Artist", "Status", "Score", "Grade", "Critical", "Warning", "Info", "Date", ""].map((h) => (
                    <th key={h} className="px-5 py-3 text-xs font-medium uppercase tracking-wider text-slate-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {scans.map((scan) => (
                  <tr key={scan.id} className="hover:bg-slate-50/60">
                    <td className="px-5 py-3 font-medium text-slate-800">{scan.release_title}</td>
                    <td className="px-5 py-3 text-slate-500">{scan.release_artist}</td>
                    <td className="px-5 py-3"><StatusDot status={scan.status} /></td>
                    <td className="px-5 py-3 tabular-nums text-xs font-semibold text-slate-700">
                      {scan.readiness_score != null ? Math.round(scan.readiness_score) : "—"}
                    </td>
                    <td className="px-5 py-3"><GradeBadge grade={scan.grade} /></td>
                    <td className="px-5 py-3 tabular-nums text-xs">
                      <span className={cn(scan.critical_count > 0 ? "font-semibold text-red-600" : "text-slate-400")}>
                        {scan.critical_count}
                      </span>
                    </td>
                    <td className="px-5 py-3 tabular-nums text-xs">
                      <span className={cn(scan.warning_count > 0 ? "font-semibold text-amber-600" : "text-slate-400")}>
                        {scan.warning_count}
                      </span>
                    </td>
                    <td className="px-5 py-3 tabular-nums text-xs text-slate-500">
                      {scan.info_count}
                    </td>
                    <td className="px-5 py-3 text-xs text-slate-400">
                      {new Date(scan.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <Link
                        href={`/scans/${scan.id}`}
                        className="text-xs font-medium text-indigo-600 hover:text-indigo-700"
                      >
                        View →
                      </Link>
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
