"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import {
  Download,
  RefreshCw,
  RotateCcw,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  AlertTriangle,
  Info,
  Sparkles,
  ShieldAlert,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getScanResults,
  resolveResult,
  type ScanDetail,
  type ScanResult,
  type ValidatedField,
} from "@/lib/api";
import { ScoreCircle } from "@/components/scan/ScoreCircle";

// ─── Helpers ──────────────────────────────────────────────────────────────────

const LAYER_LABELS: Record<string, string> = {
  ddex: "DDEX / Format",
  metadata: "DSP Metadata Rules",
  fraud: "Fraud Screening",
  artwork: "Artwork Validation",
  enrichment: "MusicBrainz Enrichment",
  bulk_registration: "Bulk Registration",
};

const LAYER_ORDER = ["ddex", "metadata", "fraud", "artwork", "enrichment", "bulk_registration"];

const SEV_ORDER: Record<string, number> = { critical: 0, error: 0, warning: 1, info: 2 };

function severityIcon(severity: string) {
  if (severity === "critical" || severity === "error")
    return <AlertTriangle className="h-4 w-4 text-red-500" />;
  if (severity === "warning")
    return <AlertTriangle className="h-4 w-4 text-amber-500" />;
  return <Info className="h-4 w-4 text-blue-500" />;
}

function SeverityBadge({ severity }: { severity: string }) {
  const cls: Record<string, string> = {
    critical: "bg-red-100 text-red-700",
    error:    "bg-red-100 text-red-700",
    warning: "bg-amber-100 text-amber-700",
    info: "bg-blue-50 text-blue-700",
  };
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold capitalize", cls[severity] ?? "bg-slate-100 text-slate-500")}>
      {severity}
    </span>
  );
}

function LayerMiniBar({ label, score, color }: { label: string; score: number; color: string }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-500">{label}</span>
        <span className="text-xs font-semibold text-slate-700 tabular-nums">{score}</span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-100">
        <div
          className={cn("h-1.5 rounded-full transition-all", color)}
          style={{ width: `${Math.min(100, score)}%` }}
        />
      </div>
    </div>
  );
}

// ─── Issue card ───────────────────────────────────────────────────────────────

function IssueCard({
  result,
  scanId,
  token,
  onResolved,
}: {
  result: ScanResult;
  scanId: string;
  token: string;
  onResolved: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [resolving, setResolving] = useState(false);

  async function handleResolve() {
    setResolving(true);
    try {
      await resolveResult(scanId, result.id, "Acknowledged", "user", token);
      onResolved(result.id);
    } catch {
      /* noop */
    } finally {
      setResolving(false);
    }
  }

  const isFraud = result.layer === "fraud";
  const isEnrichment = result.layer === "enrichment";

  if (isEnrichment) {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4">
        <div className="flex items-start gap-3">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
          <div className="flex-1 min-w-0">
            <p className="text-sm text-emerald-800">{result.message}</p>
            {result.fix_hint && (
              <p className="mt-1 text-xs font-semibold text-emerald-700">{result.fix_hint}</p>
            )}
          </div>
          {!result.resolved && (
            <button
              onClick={handleResolve}
              disabled={resolving}
              className="shrink-0 rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              {resolving ? "…" : "Dismiss"}
            </button>
          )}
          {result.resolved && (
            <span className="shrink-0 flex items-center gap-1 text-xs text-emerald-600 font-medium">
              <CheckCircle2 className="h-3.5 w-3.5" /> Dismissed
            </span>
          )}
        </div>
      </div>
    );
  }

  if (isFraud) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4">
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <p className="text-sm font-medium text-red-800">{result.message}</p>
              <SeverityBadge severity={result.severity} />
            </div>
            {result.fix_hint && (
              <p className="mt-2 rounded-md bg-red-100 px-3 py-2 text-xs font-medium text-red-700">
                ↳ {result.fix_hint}
              </p>
            )}
            <p className="mt-1.5 text-xs text-red-400 font-mono">{result.rule_id}</p>
          </div>
          {!result.resolved && (
            <button
              onClick={handleResolve}
              disabled={resolving}
              className="shrink-0 rounded-md border border-red-200 bg-white px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              {resolving ? "…" : "Dismiss"}
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={cn(
      "rounded-lg border bg-white transition-shadow hover:shadow-sm",
      result.resolved ? "border-slate-100 opacity-60" : "border-slate-200"
    )}>
      {/* Main row */}
      <div
        className="flex cursor-pointer items-start gap-3 p-4"
        onClick={() => setExpanded((e) => !e)}
      >
        <div className="mt-0.5 shrink-0">{severityIcon(result.severity)}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-4">
            <p className={cn("text-sm font-medium", result.resolved ? "line-through text-slate-400" : "text-slate-800")}>
              {result.message}
            </p>
            <div className="flex shrink-0 items-center gap-2">
              <SeverityBadge severity={result.severity} />
              {expanded ? (
                <ChevronUp className="h-4 w-4 text-slate-400" />
              ) : (
                <ChevronDown className="h-4 w-4 text-slate-400" />
              )}
            </div>
          </div>
          <p className="mt-0.5 font-mono text-xs text-slate-400">{result.rule_id}</p>
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-slate-100 bg-slate-50 px-4 py-3 space-y-3">
          {/* Fix hint — most important, visually prominent */}
          {result.fix_hint && (
            <div className="rounded-md border border-indigo-100 bg-indigo-50 px-3 py-2.5">
              <p className="text-xs font-semibold text-indigo-600 uppercase tracking-wider mb-1">Fix</p>
              <p className="text-sm text-indigo-800">{result.fix_hint}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            {result.actual_value && (
              <div>
                <p className="text-xs font-medium text-slate-500">Actual value</p>
                <p className="mt-0.5 font-mono text-xs text-slate-700">{result.actual_value}</p>
              </div>
            )}
            {result.field_path && (
              <div>
                <p className="text-xs font-medium text-slate-500">Field</p>
                <p className="mt-0.5 font-mono text-xs text-slate-700">{result.field_path}</p>
              </div>
            )}
            {result.dsp_targets.length > 0 && (
              <div>
                <p className="text-xs font-medium text-slate-500">Affects DSPs</p>
                <p className="mt-0.5 text-xs text-slate-700">{result.dsp_targets.join(", ")}</p>
              </div>
            )}
          </div>

          {/* Resolve button */}
          {!result.resolved ? (
            <button
              onClick={(e) => { e.stopPropagation(); handleResolve(); }}
              disabled={resolving}
              className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            >
              {resolving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
              Mark Resolved
            </button>
          ) : (
            <p className="flex items-center gap-1.5 text-xs font-medium text-emerald-600">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Resolved {result.resolved_at ? `on ${new Date(result.resolved_at).toLocaleDateString()}` : ""}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ScanResultsPage() {
  const params = useParams<{ scanId: string }>();
  const router = useRouter();
  const { getToken } = useAuth();
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [pollingFor, setPollingFor] = useState(true);
  const [token, setToken] = useState<string>("");
  const [reportLoading, setReportLoading] = useState(false);
  const [csvLoading, setCsvLoading] = useState(false);
  const [jsonLoading, setJsonLoading] = useState(false);
  const [bulkPdfLoading, setBulkPdfLoading] = useState(false);

  const fetchScan = useCallback(async (tok?: string) => {
    const t = tok ?? token;
    if (!t) return;
    try {
      const data = await getScanResults(params.scanId, t);
      setScan(data);
      if (data.status === "complete" || data.status === "failed") {
        setPollingFor(false);
      }
    } catch {
      setPollingFor(false);
    } finally {
      setLoading(false);
    }
  }, [params.scanId, token]);

  useEffect(() => {
    getToken().then((t) => {
      if (t) {
        setToken(t);
        fetchScan(t);
      }
    });
  }, [getToken, fetchScan]);

  // Poll while scan is running
  useEffect(() => {
    if (!pollingFor || !token) return;
    const interval = setInterval(() => fetchScan(), 3000);
    return () => clearInterval(interval);
  }, [pollingFor, token, fetchScan]);

  function handleResolved(resultId: string) {
    setScan((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        results: prev.results.map((r) =>
          r.id === resultId ? { ...r, resolved: true } : r
        ),
      };
    });
  }

  // ── Download report ──────────────────────────────────────────────────────
  async function handleDownloadReport() {
    if (!token || !scan || scan.status !== "complete") return;
    setReportLoading(true);
    try {
      const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const res = await fetch(`${API}/scans/${params.scanId}/report`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail ?? "Failed to generate report");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const cd = res.headers.get("content-disposition") ?? "";
      const match = cd.match(/filename="([^"]+)"/);
      a.download = match?.[1] ?? `SONGGATE_scan_${params.scanId.slice(0, 8)}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      /* noop — button just stops spinning */
    } finally {
      setReportLoading(false);
    }
  }

  async function handleDownloadBulkPdf() {
    if (!token || !scan || scan.status !== "complete") return;
    setBulkPdfLoading(true);
    try {
      const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const res = await fetch(`${API}/scans/${params.scanId}/export/bulk/pdf`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail ?? "Failed to generate report");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const cd = res.headers.get("content-disposition") ?? "";
      const match = cd.match(/filename="([^"]+)"/);
      a.download = match?.[1] ?? `SONGGATE_Bulk_${params.scanId.slice(0, 8)}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      /* noop */
    } finally {
      setBulkPdfLoading(false);
    }
  }

  async function handleExport(format: "csv" | "json") {
    if (!token || !scan || scan.status !== "complete") return;
    const setLoading = format === "csv" ? setCsvLoading : setJsonLoading;
    setLoading(true);
    try {
      const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const res = await fetch(`${API}/scans/${params.scanId}/export/${format}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const cd = res.headers.get("content-disposition") ?? "";
      const match = cd.match(/filename="([^"]+)"/);
      a.download = match?.[1] ?? `SONGGATE_scan_${params.scanId.slice(0, 8)}.${format}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch { /* noop */ } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    );
  }

  if (!scan) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="text-slate-500">Scan not found.</p>
      </div>
    );
  }

  // Group results by layer → then sort by severity within each layer
  const resultsByLayer: Record<string, ScanResult[]> = {};
  for (const r of scan.results) {
    (resultsByLayer[r.layer] ??= []).push(r);
  }
  for (const layer of Object.keys(resultsByLayer)) {
    resultsByLayer[layer].sort((a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9));
  }

  const isRunning = scan.status === "running" || scan.status === "queued";
  const enrichmentResults = scan.results.filter((r) => r.layer === "enrichment");
  const isBulkScan = scan.layers_run?.includes("bulk_registration");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const bulkValidatedFields = isBulkScan ? (scan.validated_fields as any) : null;
  const identifierCoverage = bulkValidatedFields?.identifier_coverage ?? null;
  // Enrichment suggestions from per-release data (Quansic ArtistMatch + WorksMatch)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const bulkEnrichmentSuggestions: any[] = isBulkScan
    ? (bulkValidatedFields?.per_release_issues ?? [])
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .filter((e: any) => e.enrichment?.suggested_isni || e.enrichment?.suggested_iswc)
    : [];
  const nonEnrichmentLayers = LAYER_ORDER.filter(
    (l) => l !== "enrichment" && l !== "bulk_registration" && resultsByLayer[l]?.length
  );

  // Per-layer scores for mini bars (simple: 100 minus proportional deductions)
  function layerScore(layer: string): number {
    const layerResults = resultsByLayer[layer] ?? [];
    const criticals = layerResults.filter((r) => !r.resolved && (r.severity === "critical" || r.severity === "error")).length;
    const warnings = layerResults.filter((r) => !r.resolved && r.severity === "warning").length;
    return Math.max(0, 100 - criticals * 20 - warnings * 7);
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Scan Results</h1>
          <p className="mt-0.5 text-xs font-mono text-slate-400">{params.scanId}</p>
        </div>
        <div className="flex items-center gap-2">
          {isRunning && (
            <div className="flex items-center gap-1.5 rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-600">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Scanning…
            </div>
          )}
          <button
            onClick={() => fetchScan()}
            className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
          <button
            onClick={() => router.push(`/releases/${scan.release_id}`)}
            className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Re-scan
          </button>
          <button
            onClick={() => handleExport("csv")}
            disabled={csvLoading || !scan || scan.status !== "complete"}
            className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-60"
          >
            {csvLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            CSV
          </button>
          <button
            onClick={() => handleExport("json")}
            disabled={jsonLoading || !scan || scan.status !== "complete"}
            className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-60"
          >
            {jsonLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            JSON
          </button>
          {isBulkScan ? (
            <button
              onClick={handleDownloadBulkPdf}
              disabled={bulkPdfLoading || scan.status !== "complete"}
              className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-indigo-700 disabled:opacity-60"
            >
              {bulkPdfLoading ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Generating…
                </>
              ) : (
                <>
                  <Download className="h-3.5 w-3.5" />
                  PDF Report
                </>
              )}
            </button>
          ) : (
            <button
              onClick={handleDownloadReport}
              disabled={reportLoading || scan.status !== "complete"}
              className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-indigo-700 disabled:opacity-60"
            >
              {reportLoading ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Generating…
                </>
              ) : (
                <>
                  <Download className="h-3.5 w-3.5" />
                  PDF
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* ── TOP: Score + layer breakdown ─────────────────────────────── */}
      <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex flex-col items-center gap-10 md:flex-row md:items-start">
          {/* Hero score circle */}
          <div className="shrink-0 flex flex-col items-center gap-4">
            <ScoreCircle
              score={scan.readiness_score}
              grade={scan.grade as "PASS" | "WARN" | "FAIL" | null}
              size="lg"
              animated
            />
            <div className="flex items-center gap-4 text-center">
              <div>
                <p className="text-2xl font-bold text-red-600 tabular-nums">{scan.critical_count}</p>
                <p className="text-xs text-slate-400">Critical</p>
              </div>
              <div className="h-8 w-px bg-slate-100" />
              <div>
                <p className="text-2xl font-bold text-amber-500 tabular-nums">{scan.warning_count}</p>
                <p className="text-xs text-slate-400">Warnings</p>
              </div>
              <div className="h-8 w-px bg-slate-100" />
              <div>
                <p className="text-2xl font-bold text-slate-400 tabular-nums">{scan.info_count}</p>
                <p className="text-xs text-slate-400">Info</p>
              </div>
            </div>
          </div>

          {/* Layer breakdown */}
          <div className="flex-1 w-full space-y-5">
            <div>
              <h2 className="text-sm font-semibold text-slate-800">Score Breakdown by Layer</h2>
              <p className="mt-0.5 text-xs text-slate-400">
                Score reflects unresolved findings only.
              </p>
            </div>

            <div className="space-y-3">
              {LAYER_ORDER.filter((l) => l !== "enrichment" && l !== "bulk_registration").map((layer) => {
                const lScore = layerScore(layer);
                const color =
                  lScore >= 80 ? "bg-emerald-500" : lScore >= 60 ? "bg-amber-400" : "bg-red-500";
                return (
                  <LayerMiniBar
                    key={layer}
                    label={LAYER_LABELS[layer] ?? layer}
                    score={lScore}
                    color={color}
                  />
                );
              })}
            </div>

            <div className="flex items-center gap-4 pt-2 text-xs text-slate-400">
              {scan.completed_at && (
                <span>
                  Completed{" "}
                  {new Date(scan.completed_at).toLocaleString(undefined, {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </span>
              )}
              {scan.layers_run.length > 0 && (
                <span>
                  Layers: {scan.layers_run.join(", ")}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── MIDDLE: Issues by layer ───────────────────────────────────── */}
      {nonEnrichmentLayers.length > 0 && (
        <div className="space-y-6">
          {nonEnrichmentLayers.map((layer) => {
            const results = resultsByLayer[layer];
            const critical = results.filter((r) => (r.severity === "critical" || r.severity === "error") && !r.resolved).length;
            const warnings = results.filter((r) => r.severity === "warning" && !r.resolved).length;

            return (
              <div key={layer} className="space-y-3">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
                    {LAYER_LABELS[layer] ?? layer}
                    {critical > 0 && (
                      <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
                        {critical} critical
                      </span>
                    )}
                    {warnings > 0 && (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
                        {warnings} warnings
                      </span>
                    )}
                  </h2>
                  <span className="text-xs text-slate-400">
                    {results.length} finding{results.length !== 1 ? "s" : ""}
                  </span>
                </div>
                <div className="space-y-2">
                  {results.map((r) => (
                    <IssueCard
                      key={r.id}
                      result={r}
                      scanId={params.scanId}
                      token={token}
                      onResolved={handleResolved}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── BULK REGISTRATION layer issues ───────────────────────────── */}
      {isBulkScan && resultsByLayer["bulk_registration"]?.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              Bulk Registration
              {(resultsByLayer["bulk_registration"] ?? []).filter((r) => r.severity === "critical" && !r.resolved).length > 0 && (
                <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
                  {(resultsByLayer["bulk_registration"] ?? []).filter((r) => r.severity === "critical" && !r.resolved).length} critical
                </span>
              )}
              {(resultsByLayer["bulk_registration"] ?? []).filter((r) => r.severity === "warning" && !r.resolved).length > 0 && (
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
                  {(resultsByLayer["bulk_registration"] ?? []).filter((r) => r.severity === "warning" && !r.resolved).length} warnings
                </span>
              )}
            </h2>
            <span className="text-xs text-slate-400">
              {(resultsByLayer["bulk_registration"] ?? []).length} finding{(resultsByLayer["bulk_registration"] ?? []).length !== 1 ? "s" : ""}
            </span>
          </div>
          <div className="space-y-2">
            {(resultsByLayer["bulk_registration"] ?? []).map((r) => (
              <IssueCard
                key={r.id}
                result={r}
                scanId={params.scanId}
                token={token}
                onResolved={handleResolved}
              />
            ))}
          </div>
        </div>
      )}

      {/* ── IDENTIFIER COVERAGE (bulk scans only) ─────────────────────── */}
      {isBulkScan && identifierCoverage && (
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800">Identifier Coverage</h2>
            <span className="text-xs text-slate-400">ISNI &amp; ISWC across catalog</span>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3 text-center">
              <p className="text-2xl font-bold text-indigo-700 tabular-nums">
                {identifierCoverage.with_isni_pct}%
              </p>
              <p className="text-xs text-slate-500 mt-0.5">
                With ISNI
                <span className="ml-1 text-slate-400">({identifierCoverage.with_isni}/{identifierCoverage.total_releases})</span>
              </p>
            </div>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3 text-center">
              <p className="text-2xl font-bold text-indigo-700 tabular-nums">
                {identifierCoverage.with_iswc_pct}%
              </p>
              <p className="text-xs text-slate-500 mt-0.5">
                With ISWC
                <span className="ml-1 text-slate-400">({identifierCoverage.with_iswc}/{identifierCoverage.total_releases})</span>
              </p>
            </div>
            <div className={cn(
              "rounded-lg border px-4 py-3 text-center",
              identifierCoverage.with_neither > 0 ? "border-amber-100 bg-amber-50" : "border-emerald-100 bg-emerald-50",
            )}>
              <p className={cn("text-2xl font-bold tabular-nums",
                identifierCoverage.with_neither > 0 ? "text-amber-600" : "text-emerald-600",
              )}>
                {identifierCoverage.with_neither}
              </p>
              <p className="text-xs text-slate-500 mt-0.5">Missing both</p>
            </div>
            <div className={cn(
              "rounded-lg border px-4 py-3 text-center",
              (identifierCoverage.isni_format_errors + identifierCoverage.iswc_format_errors) > 0
                ? "border-red-100 bg-red-50"
                : "border-emerald-100 bg-emerald-50",
            )}>
              <p className={cn("text-2xl font-bold tabular-nums",
                (identifierCoverage.isni_format_errors + identifierCoverage.iswc_format_errors) > 0
                  ? "text-red-600" : "text-emerald-600",
              )}>
                {identifierCoverage.isni_format_errors + identifierCoverage.iswc_format_errors}
              </p>
              <p className="text-xs text-slate-500 mt-0.5">Format errors</p>
            </div>
          </div>
          <p className="text-xs text-slate-500 leading-relaxed">
            ISNI and ISWC identifiers enable accurate matching in Luminate Data Enrichment.
            Missing identifiers reduce match rates for chart tracking, royalty routing, and DSP delivery.
          </p>
        </div>
      )}

      {/* ── QUANSIC ENRICHMENT SUGGESTIONS (bulk scans) ──────────────── */}
      {isBulkScan && bulkEnrichmentSuggestions.length > 0 && (
        <div className="rounded-xl border border-emerald-200 bg-white p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-emerald-600" />
              <h2 className="text-sm font-semibold text-slate-800">Enrichment Suggestions</h2>
              <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
                {bulkEnrichmentSuggestions.length} from Quansic
              </span>
              {bulkValidatedFields?.per_release_issues?.[0]?.enrichment?.mock && (
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                  mock data
                </span>
              )}
            </div>
            <span className="text-xs text-slate-400">Suggested ISNI &amp; ISWC via Luminate ArtistMatch / WorksMatch</span>
          </div>
          <div className="space-y-2">
            {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
            {bulkEnrichmentSuggestions.map((entry: any) => (
              <div key={entry.row_number} className="rounded-lg border border-emerald-100 bg-emerald-50/50 p-4">
                <div className="flex items-start gap-3">
                  <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                  <div className="flex-1 min-w-0 space-y-2">
                    <div>
                      <p className="text-sm font-medium text-slate-800">
                        Row {entry.row_number} — {entry.title}
                      </p>
                      <p className="text-xs text-slate-500">{entry.artist}</p>
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {entry.enrichment?.suggested_isni && (
                        <div className="rounded-md border border-emerald-200 bg-white px-3 py-2">
                          <p className="text-xs font-semibold text-emerald-700 uppercase tracking-wider">Suggested ISNI</p>
                          <p className="mt-0.5 font-mono text-sm text-slate-800">{entry.enrichment.suggested_isni}</p>
                          <p className="mt-0.5 text-xs text-slate-400">
                            {Math.round(entry.enrichment.isni_confidence * 100)}% confidence
                            {" · "}{entry.enrichment.isni_match_quality} match
                            {" · "}{entry.enrichment.isni_source}
                          </p>
                        </div>
                      )}
                      {entry.enrichment?.suggested_iswc && (
                        <div className="rounded-md border border-emerald-200 bg-white px-3 py-2">
                          <p className="text-xs font-semibold text-emerald-700 uppercase tracking-wider">Suggested ISWC</p>
                          <p className="mt-0.5 font-mono text-sm text-slate-800">{entry.enrichment.suggested_iswc}</p>
                          <p className="mt-0.5 text-xs text-slate-400">
                            {Math.round(entry.enrichment.iswc_confidence * 100)}% confidence
                            {" · "}{entry.enrichment.iswc_match_quality} match
                            {" · "}{entry.enrichment.iswc_source}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* No issues — green checks view */}
      {scan.status === "complete" && scan.total_issues === 0 && enrichmentResults.length === 0 && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 overflow-hidden">
          {/* Header */}
          <div className="flex items-center gap-3 px-6 py-5 border-b border-emerald-200">
            <CheckCircle2 className="h-6 w-6 text-emerald-500 shrink-0" />
            <div>
              <h2 className="text-base font-semibold text-emerald-800">All checks passed</h2>
              <p className="text-xs text-emerald-600 mt-0.5">
                Every validation rule passed. This release is ready for delivery.
              </p>
            </div>
            <span className="ml-auto rounded-full bg-emerald-100 border border-emerald-200 px-3 py-1 text-xs font-bold text-emerald-700 tracking-wider">
              100 / PASS
            </span>
          </div>

          {/* Validated fields grid */}
          {scan.validated_fields && scan.validated_fields.length > 0 && (
            <div className="px-6 py-5">
              <p className="mb-4 text-xs font-semibold uppercase tracking-widest text-emerald-700">
                Validated fields
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                {scan.validated_fields.map((field: ValidatedField) => (
                  <div key={field.label}
                    className="flex items-start gap-2.5 rounded-lg border border-emerald-100 bg-white px-4 py-3">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-slate-500">{field.label}</p>
                      {field.format === "list" && Array.isArray(field.value) ? (
                        <ul className="mt-0.5 space-y-0.5">
                          {(field.value as string[]).map((item: string, i: number) => (
                            <li key={i} className="text-sm text-slate-800 truncate">{item}</li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mt-0.5 text-sm font-medium text-slate-800 truncate">
                          {String(field.value)}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── BOTTOM: Enrichment suggestions ───────────────────────────── */}
      {enrichmentResults.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-emerald-600" />
            <h2 className="text-sm font-semibold text-slate-800">Enrichment Suggestions</h2>
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
              {enrichmentResults.length} from MusicBrainz
            </span>
          </div>
          <div className="space-y-2">
            {enrichmentResults.map((r) => (
              <IssueCard
                key={r.id}
                result={r}
                scanId={params.scanId}
                token={token}
                onResolved={handleResolved}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
