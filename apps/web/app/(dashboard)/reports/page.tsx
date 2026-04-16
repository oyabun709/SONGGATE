"use client";

import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@clerk/nextjs";
import { FileText, Download, Loader2, RefreshCw, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { listReleases, type Release } from "@/lib/api";

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

export default function ReportsPage() {
  const { getToken } = useAuth();
  const [releases, setReleases] = useState<Release[]>([]);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const token = await getToken();
      if (!token) return;
      const all = await listReleases(token);
      // Only show releases that have a completed scan
      setReleases(all.filter((r) => r.latest_scan_id && r.status === "complete"));
    } catch {
      /* empty state */
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => { fetchData(); }, [fetchData]);

  async function downloadReport(scanId: string, releaseTitle: string) {
    const token = await getToken();
    if (!token) return;
    setDownloading(scanId);
    try {
      const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const res = await fetch(`${API}/scans/${scanId}/report`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Failed to generate report");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const cd = res.headers.get("content-disposition") ?? "";
      const match = cd.match(/filename="([^"]+)"/);
      a.download = match?.[1] ?? `SONGGATE_${releaseTitle.replace(/\s+/g, "_")}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      /* silently fail */
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Reports</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Download PDF QA reports for completed scans.
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

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
          </div>
        ) : releases.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <FileText className="mb-3 h-8 w-8 text-slate-300" />
            <p className="text-sm font-medium text-slate-500">No reports yet</p>
            <p className="mt-0.5 text-xs text-slate-400">
              Reports are available after a scan completes.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left">
                  {["Release", "Artist", "Score", "Grade", "Completed", ""].map((h) => (
                    <th key={h} className="px-5 py-3 text-xs font-medium uppercase tracking-wider text-slate-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {releases.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50/60">
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                        <span className="font-medium text-slate-800 truncate max-w-[200px]">{r.title}</span>
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-slate-500">{r.artist}</td>
                    <td className="px-5 py-3.5 tabular-nums text-xs font-semibold text-slate-700">
                      {r.latest_scan_score != null ? Math.round(r.latest_scan_score) : "—"}
                    </td>
                    <td className="px-5 py-3.5">
                      <GradeBadge grade={r.latest_scan_grade ?? null} />
                    </td>
                    <td className="px-5 py-3.5 text-xs text-slate-400">
                      {new Date(r.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <button
                        onClick={() => r.latest_scan_id && downloadReport(r.latest_scan_id, r.title)}
                        disabled={downloading === r.latest_scan_id}
                        className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50 ml-auto"
                      >
                        {downloading === r.latest_scan_id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Download className="h-3.5 w-3.5" />
                        )}
                        Download PDF
                      </button>
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
