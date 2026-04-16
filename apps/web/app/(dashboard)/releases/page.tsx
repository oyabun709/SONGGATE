"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import {
  Search,
  Package,
  Plus,
  Download,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { listReleases, type Release } from "@/lib/api";

// ─── Grade badge ─────────────────────────────────────────────────────────────

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

function StatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    complete: "bg-emerald-100 text-emerald-700",
    scanning: "bg-indigo-100 text-indigo-700",
    pending: "bg-slate-100 text-slate-500",
    failed: "bg-red-100 text-red-700",
    ready: "bg-blue-100 text-blue-700",
    ingesting: "bg-amber-100 text-amber-700",
  };
  return (
    <span className={cn("inline-flex rounded-full px-2 py-0.5 text-xs font-medium capitalize", cls[status] ?? "bg-slate-100 text-slate-500")}>
      {status}
    </span>
  );
}

// ─── Sort types ───────────────────────────────────────────────────────────────

type SortField = "title" | "artist" | "created_at";
type SortDir = "asc" | "desc";

// ─── CSV export ───────────────────────────────────────────────────────────────

function exportCSV(releases: Release[]) {
  const headers = ["Title", "Artist", "UPC", "Format", "Status", "Created At"];
  const rows = releases.map((r) => [
    `"${r.title}"`,
    `"${r.artist}"`,
    r.upc ?? "",
    r.submission_format,
    r.status,
    new Date(r.created_at).toISOString(),
  ]);
  const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "releases.csv";
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ReleasesPage() {
  const { getToken } = useAuth();
  const [releases, setReleases] = useState<Release[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ field: SortField; dir: SortDir }>({
    field: "created_at",
    dir: "desc",
  });

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const token = await getToken();
      if (!token) return;
      setReleases(await listReleases(token));
    } catch {
      /* empty state */
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Filter
  const q = query.toLowerCase();
  const filtered = releases.filter((r) => {
    if (!q) return true;
    return (
      r.title.toLowerCase().includes(q) ||
      r.artist.toLowerCase().includes(q) ||
      (r.upc ?? "").includes(q)
    );
  });

  // Sort
  const sorted = [...filtered].sort((a, b) => {
    const va = a[sort.field] ?? "";
    const vb = b[sort.field] ?? "";
    const cmp = String(va).localeCompare(String(vb));
    return sort.dir === "asc" ? cmp : -cmp;
  });

  function toggleSort(field: SortField) {
    setSort((prev) => ({
      field,
      dir: prev.field === field && prev.dir === "asc" ? "desc" : "asc",
    }));
  }

  function SortIcon({ field }: { field: SortField }) {
    if (sort.field !== field) return <ChevronsUpDown className="ml-1 h-3 w-3 text-slate-300" />;
    return sort.dir === "asc" ? (
      <ChevronUp className="ml-1 h-3 w-3 text-indigo-500" />
    ) : (
      <ChevronDown className="ml-1 h-3 w-3 text-indigo-500" />
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Release History</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            All releases with their latest scan scores — {releases.length} total.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => exportCSV(sorted)}
            disabled={sorted.length === 0}
            className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40"
          >
            <Download className="h-3.5 w-3.5" />
            Export CSV
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

      {/* Search + filter bar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by title, artist, UPC…"
            className="w-full rounded-md border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm text-slate-800 placeholder-slate-400 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
          />
        </div>
        {query && (
          <button
            onClick={() => setQuery("")}
            className="text-xs font-medium text-slate-400 hover:text-slate-600"
          >
            Clear
          </button>
        )}
        <span className="ml-auto text-xs text-slate-400">
          {sorted.length} of {releases.length}
        </span>
      </div>

      {/* Table */}
      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
          </div>
        ) : sorted.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Package className="mb-3 h-8 w-8 text-slate-300" />
            <p className="text-sm font-medium text-slate-500">
              {query ? "No releases match your search" : "No releases yet"}
            </p>
            {!query && (
              <Link
                href="/releases/new"
                className="mt-4 flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
              >
                <Plus className="h-3.5 w-3.5" />
                New Scan
              </Link>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left">
                  <th
                    className="cursor-pointer px-5 py-3 text-xs font-medium uppercase tracking-wider text-slate-400 hover:text-slate-600"
                    onClick={() => toggleSort("title")}
                  >
                    <span className="flex items-center">
                      Release <SortIcon field="title" />
                    </span>
                  </th>
                  <th
                    className="cursor-pointer px-5 py-3 text-xs font-medium uppercase tracking-wider text-slate-400 hover:text-slate-600"
                    onClick={() => toggleSort("artist")}
                  >
                    <span className="flex items-center">
                      Artist <SortIcon field="artist" />
                    </span>
                  </th>
                  <th className="px-5 py-3 text-xs font-medium uppercase tracking-wider text-slate-400">
                    UPC
                  </th>
                  <th className="px-5 py-3 text-xs font-medium uppercase tracking-wider text-slate-400">
                    Score
                  </th>
                  <th className="px-5 py-3 text-xs font-medium uppercase tracking-wider text-slate-400">
                    Grade
                  </th>
                  <th className="px-5 py-3 text-xs font-medium uppercase tracking-wider text-slate-400">
                    Status
                  </th>
                  <th
                    className="cursor-pointer px-5 py-3 text-xs font-medium uppercase tracking-wider text-slate-400 hover:text-slate-600"
                    onClick={() => toggleSort("created_at")}
                  >
                    <span className="flex items-center">
                      Date <SortIcon field="created_at" />
                    </span>
                  </th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {sorted.map((r) => (
                  <tr key={r.id} className="group hover:bg-slate-50/60">
                    <td className="px-5 py-3.5">
                      <span className="font-medium text-slate-800">{r.title}</span>
                    </td>
                    <td className="px-5 py-3.5 text-slate-500">{r.artist}</td>
                    <td className="px-5 py-3.5 font-mono text-xs text-slate-400">
                      {r.upc ?? "—"}
                    </td>
                    <td className="px-5 py-3.5">
                      {r.latest_scan_score != null ? (
                        <span className="tabular-nums text-xs font-semibold text-slate-700">
                          {Math.round(r.latest_scan_score)}
                        </span>
                      ) : (
                        <span className="text-xs text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3.5">
                      <GradeBadge grade={r.latest_scan_grade ?? null} />
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="px-5 py-3.5 text-xs text-slate-400">
                      {new Date(r.created_at).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })}
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <div className="flex items-center justify-end gap-3 opacity-0 group-hover:opacity-100 transition-opacity">
                        {r.latest_scan_id && (
                          <Link
                            href={`/scans/${r.latest_scan_id}`}
                            className="text-xs font-medium text-slate-500 hover:text-slate-700"
                          >
                            View Scan
                          </Link>
                        )}
                        <Link
                          href={`/releases/${r.id}`}
                          className="text-xs font-medium text-slate-500 hover:text-slate-700"
                        >
                          Details
                        </Link>
                        <Link
                          href="/releases/new"
                          className="text-xs font-medium text-indigo-600 hover:text-indigo-700"
                        >
                          New Scan →
                        </Link>
                      </div>
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
