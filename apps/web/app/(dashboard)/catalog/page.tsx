"use client";

import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@clerk/nextjs";
import {
  Database,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  Loader2,
  RefreshCw,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface CatalogStats {
  total_releases: number;
  unique_eans: number;
  conflicted_eans: number;
  artist_variants: number;
  isni_coverage: number;
  iswc_coverage: number;
}

interface EANConflict {
  ean: string;
  artist_variants: string[];
  title_variants: string[];
  has_artist_conflict: boolean;
  has_title_conflict: boolean;
  has_isni_conflict: boolean;
  scan_count: number;
  first_seen: string | null;
  last_seen: string | null;
  severity: "critical" | "warning";
}

interface ArtistVariant {
  normalized: string;
  raw_variants: string[];
  ean_count: number;
  isni_status: "present" | "partial" | "missing" | "conflicting";
}

interface Coverage {
  total_releases: number;
  with_isni: number;
  with_iswc: number;
  with_both: number;
  with_neither: number;
  isni_pct: number;
  iswc_pct: number;
}

interface PaginatedConflicts {
  data: EANConflict[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

interface PaginatedVariants {
  data: ArtistVariant[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

const PER_PAGE = 25;

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric", month: "short", day: "numeric",
  });
}

// ── Pagination control ────────────────────────────────────────────────────────

function Pagination({
  page,
  totalPages,
  total,
  perPage,
  loading,
  onPage,
}: {
  page: number;
  totalPages: number;
  total: number;
  perPage: number;
  loading: boolean;
  onPage: (p: number) => void;
}) {
  const start = Math.min((page - 1) * perPage + 1, total);
  const end   = Math.min(page * perPage, total);
  return (
    <div className="flex items-center justify-between pt-2">
      <p className="text-xs text-slate-400 tabular-nums">
        {total === 0 ? "No results" : `Showing ${start}–${end} of ${total}`}
      </p>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onPage(page - 1)}
          disabled={page <= 1 || loading}
          className="flex h-7 w-7 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
          aria-label="Previous page"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <span className="min-w-[4rem] text-center text-xs tabular-nums text-slate-500">
          {page} / {totalPages}
        </span>
        <button
          onClick={() => onPage(page + 1)}
          disabled={page >= totalPages || loading}
          className="flex h-7 w-7 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
          aria-label="Next page"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  color = "slate",
}: {
  label: string;
  value: string | number;
  sub?: string;
  color?: "slate" | "red" | "amber" | "indigo" | "emerald";
}) {
  const textCls: Record<string, string> = {
    slate:   "text-slate-800",
    red:     "text-red-600",
    amber:   "text-amber-600",
    indigo:  "text-indigo-700",
    emerald: "text-emerald-600",
  };
  const borderCls: Record<string, string> = {
    slate:   "border-slate-100 bg-slate-50",
    red:     "border-red-100 bg-red-50",
    amber:   "border-amber-100 bg-amber-50",
    indigo:  "border-indigo-100 bg-indigo-50",
    emerald: "border-emerald-100 bg-emerald-50",
  };
  return (
    <div className={cn("rounded-xl border px-5 py-4", borderCls[color])}>
      <p className={cn("text-3xl font-bold tabular-nums", textCls[color])}>{value}</p>
      <p className="mt-1 text-xs font-semibold text-slate-700">{label}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-400">{sub}</p>}
    </div>
  );
}

// ── EAN conflict row ──────────────────────────────────────────────────────────

function ConflictRow({ conflict }: { conflict: EANConflict }) {
  const [expanded, setExpanded] = useState(false);
  const isCritical = conflict.severity === "critical";
  return (
    <div className={cn(
      "rounded-lg border transition-shadow",
      isCritical ? "border-red-200 bg-red-50/60" : "border-amber-100 bg-amber-50/40",
    )}>
      <div
        className="flex cursor-pointer items-center gap-3 px-4 py-3"
        onClick={() => setExpanded((e) => !e)}
      >
        <AlertTriangle className={cn("h-4 w-4 shrink-0", isCritical ? "text-red-500" : "text-amber-500")} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="font-mono text-sm font-semibold text-slate-800">{conflict.ean}</span>
            <span className={cn(
              "rounded-full px-2 py-0.5 text-xs font-semibold uppercase",
              isCritical ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700",
            )}>
              {conflict.severity}
            </span>
            {conflict.has_artist_conflict && (
              <span className="rounded-full bg-red-50 border border-red-200 px-2 py-0.5 text-xs text-red-600">artist conflict</span>
            )}
            {conflict.has_title_conflict && (
              <span className="rounded-full bg-amber-50 border border-amber-200 px-2 py-0.5 text-xs text-amber-600">title conflict</span>
            )}
            {conflict.has_isni_conflict && (
              <span className="rounded-full bg-red-50 border border-red-200 px-2 py-0.5 text-xs text-red-600">ISNI conflict</span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-slate-400">
            {conflict.scan_count} submission{conflict.scan_count !== 1 ? "s" : ""} ·
            First seen {fmtDate(conflict.first_seen)} ·
            Last seen {fmtDate(conflict.last_seen)}
          </p>
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 shrink-0 text-slate-400" />
        ) : (
          <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" />
        )}
      </div>

      {expanded && (
        <div className="border-t border-slate-100 bg-white/70 px-4 py-3 space-y-3 rounded-b-lg">
          {conflict.artist_variants.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Artist variants</p>
              <ul className="space-y-0.5">
                {conflict.artist_variants.map((v, i) => (
                  <li key={i} className="text-sm text-slate-800 font-medium">{v}</li>
                ))}
              </ul>
            </div>
          )}
          {conflict.title_variants.length > 0 && conflict.title_variants.length > 1 && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Title variants</p>
              <ul className="space-y-0.5">
                {conflict.title_variants.map((v, i) => (
                  <li key={i} className="text-sm text-slate-700">{v}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-xs text-slate-500 bg-indigo-50 rounded-md px-3 py-2">
            Standardize release data across all submissions. Contact your distributor to reconcile historical records.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Artist variant row ────────────────────────────────────────────────────────

const ISNI_STATUS_BADGE: Record<string, string> = {
  present:     "bg-emerald-100 text-emerald-700",
  partial:     "bg-amber-100 text-amber-700",
  missing:     "bg-slate-100 text-slate-500",
  conflicting: "bg-red-100 text-red-700",
};

function ArtistVariantRow({ variant }: { variant: ArtistVariant }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded-lg border border-amber-100 bg-amber-50/30 transition-shadow">
      <div
        className="flex cursor-pointer items-center gap-3 px-4 py-3"
        onClick={() => setExpanded((e) => !e)}
      >
        <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-mono text-slate-600">{variant.normalized}</span>
            <span className="text-xs text-slate-400">→</span>
            <span className="text-sm text-slate-800 font-medium">
              {variant.raw_variants.slice(0, 2).map(v => `"${v}"`).join(", ")}
              {variant.raw_variants.length > 2 && ` +${variant.raw_variants.length - 2} more`}
            </span>
          </div>
          <p className="mt-0.5 text-xs text-slate-400">
            {variant.ean_count} EAN{variant.ean_count !== 1 ? "s" : ""}
          </p>
        </div>
        <span className={cn(
          "rounded-full px-2 py-0.5 text-xs font-semibold capitalize",
          ISNI_STATUS_BADGE[variant.isni_status] ?? "bg-slate-100 text-slate-500",
        )}>
          ISNI: {variant.isni_status}
        </span>
        {expanded ? (
          <ChevronUp className="h-4 w-4 shrink-0 text-slate-400" />
        ) : (
          <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" />
        )}
      </div>

      {expanded && (
        <div className="border-t border-slate-100 bg-white/70 px-4 py-3 rounded-b-lg">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">All raw variants</p>
          <ul className="space-y-0.5 mb-3">
            {variant.raw_variants.map((v, i) => (
              <li key={i} className="text-sm text-slate-800">{v}</li>
            ))}
          </ul>
          <p className="text-xs text-slate-500 bg-indigo-50 rounded-md px-3 py-2">
            Use a single canonical artist name format across all submissions.
            Inconsistent separators (&amp; vs , vs and) reduce ISNI match rates in
            Luminate Data Enrichment.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Coverage bar ──────────────────────────────────────────────────────────────

function CoverageBar({ label, pct, count, total }: { label: string; pct: number; count: number; total: number }) {
  const color = pct >= 80 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-400" : "bg-red-500";
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-slate-700">{label}</span>
        <span className="tabular-nums text-slate-500">
          {count} / {total} <span className="font-semibold">({pct}%)</span>
        </span>
      </div>
      <div className="h-2 rounded-full bg-slate-100">
        <div className={cn("h-2 rounded-full transition-all duration-700", color)}
          style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center">
      <Database className="mx-auto h-8 w-8 text-slate-300 mb-3" />
      <p className="text-sm text-slate-500">{message}</p>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function CatalogPage() {
  const { getToken } = useAuth();
  const [token, setToken]             = useState("");
  const [loading, setLoading]         = useState(true);
  const [refreshing, setRefreshing]   = useState(false);
  const [stats, setStats]             = useState<CatalogStats | null>(null);
  const [conflictData, setConflictData] = useState<PaginatedConflicts | null>(null);
  const [variantData, setVariantData]   = useState<PaginatedVariants | null>(null);
  const [coverage, setCoverage]       = useState<Coverage | null>(null);
  const [error, setError]             = useState<string | null>(null);

  // Pagination state
  const [conflictPage, setConflictPage] = useState(1);
  const [variantPage, setVariantPage]   = useState(1);
  const [conflictLoading, setConflictLoading] = useState(false);
  const [variantLoading, setVariantLoading]   = useState(false);

  const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  const fetchConflicts = useCallback(async (tok: string, page: number) => {
    setConflictLoading(true);
    try {
      const res = await fetch(
        `${API}/catalog/conflicts?page=${page}&per_page=${PER_PAGE}`,
        { headers: { Authorization: `Bearer ${tok}` } },
      );
      if (!res.ok) throw new Error("Failed to load conflicts");
      const data: PaginatedConflicts = await res.json();
      setConflictData(data);
    } finally {
      setConflictLoading(false);
    }
  }, [API]);

  const fetchVariants = useCallback(async (tok: string, page: number) => {
    setVariantLoading(true);
    try {
      const res = await fetch(
        `${API}/catalog/artist-variants?page=${page}&per_page=${PER_PAGE}`,
        { headers: { Authorization: `Bearer ${tok}` } },
      );
      if (!res.ok) throw new Error("Failed to load artist variants");
      const data: PaginatedVariants = await res.json();
      setVariantData(data);
    } finally {
      setVariantLoading(false);
    }
  }, [API]);

  const fetchAll = useCallback(async (tok: string, silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    setError(null);

    const headers = { Authorization: `Bearer ${tok}` };

    try {
      const [statsRes, conflictsRes, variantsRes, coverageRes] = await Promise.all([
        fetch(`${API}/catalog/stats`,                                                  { headers }),
        fetch(`${API}/catalog/conflicts?page=1&per_page=${PER_PAGE}`,                 { headers }),
        fetch(`${API}/catalog/artist-variants?page=1&per_page=${PER_PAGE}`,           { headers }),
        fetch(`${API}/catalog/coverage`,                                               { headers }),
      ]);

      if (!statsRes.ok) throw new Error("Failed to load catalog stats");

      const [s, c, v, cov] = await Promise.all([
        statsRes.json(),
        conflictsRes.json(),
        variantsRes.json(),
        coverageRes.json(),
      ]);

      setStats(s);
      setConflictData(c);
      setConflictPage(1);
      setVariantData(v);
      setVariantPage(1);
      setCoverage(cov);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [API]);

  useEffect(() => {
    getToken().then((t) => {
      if (t) {
        setToken(t);
        fetchAll(t);
      }
    });
  }, [getToken, fetchAll]);

  const handleConflictPage = (p: number) => {
    setConflictPage(p);
    fetchConflicts(token, p);
  };

  const handleVariantPage = (p: number) => {
    setVariantPage(p);
    fetchVariants(token, p);
  };

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    );
  }

  const isEmpty = !stats || stats.total_releases === 0;
  const conflicts = conflictData?.data ?? [];
  const variants  = variantData?.data  ?? [];

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 flex items-center gap-2">
            <Database className="h-6 w-6 text-indigo-600" />
            Catalog Index
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Cross-release metadata intelligence built from your scan history.
          </p>
        </div>
        <button
          onClick={() => token && fetchAll(token, true)}
          disabled={refreshing}
          className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-60"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Stats row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total Releases Indexed"
          value={stats?.total_releases ?? 0}
          sub="Across all bulk scans"
          color="slate"
        />
        <StatCard
          label="Unique EANs"
          value={stats?.unique_eans ?? 0}
          sub="Distinct barcodes in catalog"
          color="indigo"
        />
        <StatCard
          label="EANs with Conflicts"
          value={stats?.conflicted_eans ?? 0}
          sub={stats?.conflicted_eans ? "Require reconciliation" : "No conflicts detected"}
          color={stats?.conflicted_eans ? "red" : "emerald"}
        />
        <StatCard
          label="Artist Name Variants"
          value={stats?.artist_variants ?? 0}
          sub={stats?.artist_variants ? "Disambiguation needed" : "Consistent naming"}
          color={stats?.artist_variants ? "amber" : "emerald"}
        />
      </div>

      {isEmpty && (
        <EmptyState message="No catalog data yet. Run a bulk registration scan to start building your catalog index." />
      )}

      {!isEmpty && (
        <>
          {/* EAN Conflicts */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
                EAN Conflicts
                {conflicts.filter(c => c.severity === "critical").length > 0 && (
                  <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
                    {conflicts.filter(c => c.severity === "critical").length} critical
                  </span>
                )}
                {conflicts.filter(c => c.severity === "warning").length > 0 && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
                    {conflicts.filter(c => c.severity === "warning").length} warnings
                  </span>
                )}
              </h2>
              <span className="text-xs text-slate-400">Same EAN, different metadata across scans</span>
            </div>

            {conflicts.length === 0 && !conflictLoading ? (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-5 py-4 text-center">
                <p className="text-sm font-medium text-emerald-700">No EAN conflicts detected</p>
                <p className="text-xs text-emerald-600 mt-0.5">
                  All EANs are consistent across your catalog submissions.
                </p>
              </div>
            ) : (
              <div className={cn("space-y-2", conflictLoading && "opacity-60 pointer-events-none")}>
                {conflicts.map(c => <ConflictRow key={c.ean} conflict={c} />)}
                {conflictData && conflictData.total_pages > 1 && (
                  <Pagination
                    page={conflictPage}
                    totalPages={conflictData.total_pages}
                    total={conflictData.total}
                    perPage={PER_PAGE}
                    loading={conflictLoading}
                    onPage={handleConflictPage}
                  />
                )}
              </div>
            )}
          </div>

          {/* Artist Name Variants */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
                Artist Name Variants
                {variantData && variantData.total > 0 && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
                    {variantData.total} artist{variantData.total !== 1 ? "s" : ""}
                  </span>
                )}
              </h2>
              <span className="text-xs text-slate-400">Same normalized name, different raw formats</span>
            </div>

            {variants.length === 0 && !variantLoading ? (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-5 py-4 text-center">
                <p className="text-sm font-medium text-emerald-700">No artist name variants detected</p>
                <p className="text-xs text-emerald-600 mt-0.5">
                  All artist names are submitted consistently across your catalog.
                </p>
              </div>
            ) : (
              <div className={cn("space-y-2", variantLoading && "opacity-60 pointer-events-none")}>
                {variants.map(v => <ArtistVariantRow key={v.normalized} variant={v} />)}
                {variantData && variantData.total_pages > 1 && (
                  <Pagination
                    page={variantPage}
                    totalPages={variantData.total_pages}
                    total={variantData.total}
                    perPage={PER_PAGE}
                    loading={variantLoading}
                    onPage={handleVariantPage}
                  />
                )}
              </div>
            )}
          </div>

          {/* Identifier Coverage */}
          {coverage && (
            <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-5">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-800">
                  Identifier Coverage Across Catalog
                </h2>
                <span className="text-xs text-slate-400">
                  {coverage.total_releases} releases indexed
                </span>
              </div>

              <div className="space-y-4">
                <CoverageBar
                  label="With ISNI"
                  pct={coverage.isni_pct}
                  count={coverage.with_isni}
                  total={coverage.total_releases}
                />
                <CoverageBar
                  label="With ISWC"
                  pct={coverage.iswc_pct}
                  count={coverage.with_iswc}
                  total={coverage.total_releases}
                />
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3 text-center">
                  <p className="text-xl font-bold text-indigo-700 tabular-nums">{coverage.with_both}</p>
                  <p className="text-xs text-slate-500 mt-0.5">With both</p>
                </div>
                <div className={cn(
                  "rounded-lg border px-4 py-3 text-center",
                  coverage.with_neither > 0 ? "border-amber-100 bg-amber-50" : "border-emerald-100 bg-emerald-50",
                )}>
                  <p className={cn("text-xl font-bold tabular-nums",
                    coverage.with_neither > 0 ? "text-amber-600" : "text-emerald-600",
                  )}>
                    {coverage.with_neither}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">Missing both</p>
                </div>
                <div className="rounded-lg border border-slate-100 bg-slate-50 px-4 py-3 text-center">
                  <p className="text-xl font-bold text-slate-700 tabular-nums">
                    {coverage.total_releases}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">Total indexed</p>
                </div>
              </div>

              <div className="flex items-start gap-2 rounded-lg bg-indigo-50 border border-indigo-100 px-4 py-3">
                <Info className="h-4 w-4 shrink-0 text-indigo-500 mt-0.5" />
                <p className="text-xs text-indigo-800 leading-relaxed">
                  Connect to{" "}
                  <span className="font-semibold">Luminate Data Enrichment</span>{" "}
                  to automatically resolve missing ISNIs (via ArtistMatch) and ISWCs
                  (via WorksMatch) across your catalog.
                  Higher identifier coverage reduces downstream matching failures
                  in chart tracking, royalty routing, and DSP delivery.
                </p>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
