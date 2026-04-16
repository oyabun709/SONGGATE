"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import {
  Package,
  Calendar,
  Music,
  Hash,
  Plus,
  ArrowLeft,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  ExternalLink,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getRelease, listReleaseScanHistory, type Release, type Scan } from "@/lib/api";

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

function ScanStatusIcon({ status }: { status: string }) {
  if (status === "complete") return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-red-500" />;
  if (status === "running") return <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />;
  return <Clock className="h-4 w-4 text-slate-400" />;
}

export default function ReleaseDetailPage() {
  const params = useParams<{ releaseId: string }>();
  const router = useRouter();
  const { getToken } = useAuth();
  const [release, setRelease] = useState<Release | null>(null);
  const [scans, setScans] = useState<Scan[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    const token = await getToken();
    if (!token) return;
    try {
      const [rel, scanHistory] = await Promise.all([
        getRelease(params.releaseId, token),
        listReleaseScanHistory(params.releaseId, token),
      ]);
      setRelease(rel);
      setScans(scanHistory);
    } catch {
      /* noop */
    } finally {
      setLoading(false);
    }
  }, [params.releaseId, getToken]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    );
  }

  if (!release) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3">
        <Package className="h-10 w-10 text-slate-300" />
        <p className="text-slate-500">Release not found.</p>
        <Link href="/releases" className="text-xs font-medium text-indigo-600 hover:text-indigo-700">
          ← Back to releases
        </Link>
      </div>
    );
  }

  const latestScan = scans[0] ?? null;

  const FORMAT_LABELS: Record<string, string> = {
    DDEX_ERN_43: "DDEX ERN 4.3",
    DDEX_ERN_42: "DDEX ERN 4.2",
    CSV: "CSV",
    JSON: "JSON",
  };

  return (
    <div className="space-y-6">
      {/* Back + header */}
      <div>
        <button
          onClick={() => router.back()}
          className="mb-3 flex items-center gap-1.5 text-xs font-medium text-slate-400 hover:text-slate-600"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back
        </button>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">{release.title}</h1>
            <p className="mt-0.5 text-sm text-slate-500">{release.artist}</p>
          </div>
          <Link
            href="/releases/new"
            className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700"
          >
            <Plus className="h-4 w-4" />
            New Scan
          </Link>
        </div>
      </div>

      {/* Release metadata */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { icon: Music, label: "Format", value: FORMAT_LABELS[release.submission_format] ?? release.submission_format },
          { icon: Hash, label: "UPC", value: release.upc ?? "—" },
          { icon: Calendar, label: "Release Date", value: release.release_date ? new Date(release.release_date).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "—" },
          { icon: Package, label: "Status", value: release.status },
        ].map(({ icon: Icon, label, value }) => (
          <div key={label} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-1.5 text-xs font-medium text-slate-400 mb-1">
              <Icon className="h-3.5 w-3.5" />
              {label}
            </div>
            <p className="text-sm font-semibold text-slate-800 truncate capitalize">{value}</p>
          </div>
        ))}
      </div>

      {/* Latest scan summary */}
      {latestScan && (
        <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-slate-900">Latest Scan</h2>
            <Link
              href={`/scans/${latestScan.id}`}
              className="flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-700"
            >
              View full results <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <p className="text-xs text-slate-400">Grade</p>
              <div className="mt-1"><GradeBadge grade={latestScan.grade} /></div>
            </div>
            <div>
              <p className="text-xs text-slate-400">Score</p>
              <p className="mt-1 text-sm font-bold text-slate-800 tabular-nums">
                {latestScan.readiness_score != null ? Math.round(latestScan.readiness_score) : "—"}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-400">Issues</p>
              <p className="mt-1 text-sm font-bold text-slate-800 tabular-nums">
                <span className="text-red-600">{latestScan.critical_count}</span>
                <span className="text-slate-300 mx-1">/</span>
                <span className="text-amber-600">{latestScan.warning_count}</span>
                <span className="text-slate-300 mx-1">/</span>
                <span className="text-slate-400">{latestScan.info_count}</span>
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-400">Completed</p>
              <p className="mt-1 text-sm font-semibold text-slate-800">
                {latestScan.completed_at
                  ? new Date(latestScan.completed_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
                  : "—"}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Scan history */}
      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 className="text-sm font-semibold text-slate-900">Scan History</h2>
          <span className="text-xs text-slate-400">{scans.length} scan{scans.length !== 1 ? "s" : ""}</span>
        </div>

        {scans.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <AlertTriangle className="mb-3 h-8 w-8 text-slate-200" />
            <p className="text-sm font-medium text-slate-500">No scans yet</p>
            <p className="mt-0.5 text-xs text-slate-400">Run a scan to see QA results here.</p>
            <Link
              href="/releases/new"
              className="mt-4 flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
            >
              <Plus className="h-3.5 w-3.5" /> New Scan
            </Link>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left">
                  {["Status", "Grade", "Score", "Critical", "Warnings", "Date", ""].map((h) => (
                    <th key={h} className="px-5 py-3 text-xs font-medium uppercase tracking-wider text-slate-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {scans.map((scan, i) => (
                  <tr key={scan.id} className="hover:bg-slate-50/60">
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-1.5">
                        <ScanStatusIcon status={scan.status} />
                        <span className="capitalize text-xs text-slate-500">{scan.status}</span>
                      </div>
                    </td>
                    <td className="px-5 py-3"><GradeBadge grade={scan.grade} /></td>
                    <td className="px-5 py-3 tabular-nums text-xs font-semibold text-slate-700">
                      {scan.readiness_score != null ? Math.round(scan.readiness_score) : "—"}
                    </td>
                    <td className="px-5 py-3 tabular-nums text-xs font-semibold text-red-600">{scan.critical_count}</td>
                    <td className="px-5 py-3 tabular-nums text-xs font-semibold text-amber-600">{scan.warning_count}</td>
                    <td className="px-5 py-3 text-xs text-slate-400">
                      {new Date(scan.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                      {i === 0 && <span className="ml-1.5 rounded-full bg-indigo-100 px-1.5 py-0.5 text-xs font-medium text-indigo-600">Latest</span>}
                    </td>
                    <td className="px-5 py-3 text-right">
                      {scan.status === "complete" && (
                        <Link
                          href={`/scans/${scan.id}`}
                          className="text-xs font-medium text-indigo-600 hover:text-indigo-700"
                        >
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
