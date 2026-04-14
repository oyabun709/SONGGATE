"use client";

import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@clerk/nextjs";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  Cell,
  Legend,
} from "recharts";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  RefreshCw,
  Share2,
  Copy,
  CheckCheck,
  ShieldAlert,
  Loader2,
  AlertTriangle,
  Info,
  Zap,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getAnalyticsOverview,
  refreshAnalyticsOverview,
  createShareLink,
  type AnalyticsOverview,
} from "@/lib/api";

// ─── Constants ────────────────────────────────────────────────────────────────

const SEV_COLOR: Record<string, string> = {
  critical: "#ef4444",
  warning:  "#f59e0b",
  info:     "#6366f1",
};

const LAYER_COLOR: Record<string, string> = {
  ddex:       "#8b5cf6",
  metadata:   "#3b82f6",
  fraud:      "#ef4444",
  audio:      "#f59e0b",
  artwork:    "#ec4899",
  enrichment: "#10b981",
};

const DSP_LABELS: Record<string, string> = {
  spotify: "Spotify",
  apple:   "Apple Music",
  youtube: "YouTube Music",
  amazon:  "Amazon Music",
  tiktok:  "TikTok",
};

// ─── Small helpers ────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: "green" | "red" | "amber" | "indigo";
}) {
  const colors = {
    green:  { bg: "bg-emerald-50", text: "text-emerald-600", val: "text-emerald-700" },
    red:    { bg: "bg-red-50",     text: "text-red-600",     val: "text-red-700"     },
    amber:  { bg: "bg-amber-50",   text: "text-amber-600",   val: "text-amber-700"   },
    indigo: { bg: "bg-indigo-50",  text: "text-indigo-600",  val: "text-indigo-700"  },
  };
  const c = accent ? colors[accent] : { bg: "bg-slate-50", text: "text-slate-500", val: "text-slate-900" };
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</p>
      <p className={cn("mt-2 text-3xl font-bold tabular-nums", c.val)}>{value}</p>
      {sub && <p className={cn("mt-1 text-xs font-medium", c.text)}>{sub}</p>}
    </div>
  );
}

function TrendPill({ value }: { value: number }) {
  if (Math.abs(value) < 0.1)
    return (
      <span className="inline-flex items-center gap-0.5 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
        <Minus className="h-3 w-3" /> 0.0pp
      </span>
    );
  const up = value > 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-xs font-semibold",
        up ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"
      )}
    >
      {up ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
      {up ? "+" : ""}{value.toFixed(1)}pp
    </span>
  );
}

function SevIcon({ severity }: { severity: string }) {
  if (severity === "critical") return <AlertTriangle className="h-3.5 w-3.5 text-red-500" />;
  if (severity === "warning")  return <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />;
  return <Info className="h-3.5 w-3.5 text-blue-400" />;
}

// Recharts custom tooltip
function DarkTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs shadow-xl">
      <p className="mb-1 font-medium text-slate-300">{label}</p>
      {payload.map((p: any) => (
        <p key={p.name} style={{ color: p.color }} className="tabular-nums">
          {p.name}: <span className="font-semibold">{p.value}</span>
        </p>
      ))}
    </div>
  );
}

// ─── Share modal ──────────────────────────────────────────────────────────────

function ShareModal({
  token: apiToken,
  onClose,
}: {
  token: string;
  onClose: () => void;
}) {
  const [shareToken, setShareToken] = useState<string | null>(null);
  const [loading, setLoading]       = useState(false);
  const [copied, setCopied]         = useState(false);

  async function generate() {
    setLoading(true);
    try {
      const res = await createShareLink(apiToken);
      setShareToken(res.token);
    } catch {
      /* noop */
    } finally {
      setLoading(false);
    }
  }

  const shareUrl = shareToken
    ? `${typeof window !== "undefined" ? window.location.origin : ""}/share/${shareToken}`
    : null;

  function copyLink() {
    if (!shareUrl) return;
    navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="relative w-full max-w-md rounded-2xl border border-slate-200 bg-white p-7 shadow-2xl">
        <button
          onClick={onClose}
          className="absolute right-4 top-4 rounded-full p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="flex items-center gap-3 mb-5">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-indigo-50">
            <Share2 className="h-5 w-5 text-indigo-600" />
          </span>
          <div>
            <h2 className="text-base font-semibold text-slate-900">Share Analytics</h2>
            <p className="text-xs text-slate-500">Anonymized aggregate data — no client names</p>
          </div>
        </div>

        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 mb-5 text-xs text-amber-800">
          <strong>What gets shared:</strong> aggregate counts, rule-level breakdowns, DSP pass rates, fraud signal rates, and velocity trends — all without any organization or release identifiers.
        </div>

        {!shareToken ? (
          <button
            onClick={generate}
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-60"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
            Generate Share Link
          </button>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
              <span className="flex-1 truncate font-mono text-xs text-slate-700">{shareUrl}</span>
              <button
                onClick={copyLink}
                className="shrink-0 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 transition-colors"
              >
                {copied ? (
                  <span className="flex items-center gap-1 text-emerald-600">
                    <CheckCheck className="h-3.5 w-3.5" /> Copied
                  </span>
                ) : (
                  <span className="flex items-center gap-1">
                    <Copy className="h-3.5 w-3.5" /> Copy
                  </span>
                )}
              </button>
            </div>
            <p className="text-xs text-slate-400 text-center">Valid for 7 days · Read-only · No login required</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const { getToken } = useAuth();
  const [token, setToken]       = useState("");
  const [data, setData]         = useState<AnalyticsOverview | null>(null);
  const [loading, setLoading]   = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showShare, setShowShare]   = useState(false);

  const fetchData = useCallback(
    async (tok?: string, forceRefresh = false) => {
      const t = tok ?? token;
      if (!t) return;
      forceRefresh ? setRefreshing(true) : setLoading(true);
      try {
        const overview = forceRefresh
          ? await refreshAnalyticsOverview(t)
          : await getAnalyticsOverview(t);
        setData(overview);
      } catch {
        /* empty */
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [token]
  );

  useEffect(() => {
    getToken().then((t) => {
      if (t) { setToken(t); fetchData(t); }
    });
  }, [getToken, fetchData]);

  const cachedLabel = data
    ? `Data as of ${new Date(data.cached_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
    : null;

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    );
  }

  const agg = data?.aggregate;
  const topIssues = data?.top_issues ?? [];
  const dspMatrix = data?.dsp_matrix ?? [];
  const fraud     = data?.fraud_signals;
  const velocity  = data?.velocity ?? [];

  // Enrich top-issues for Recharts (need a short label that fits the bar)
  const barData = topIssues.map((t) => ({
    ...t,
    label: t.rule_label.length > 28 ? t.rule_label.slice(0, 26) + "…" : t.rule_label,
  }));

  return (
    <div className="space-y-8">
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Analytics</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Corpus-level intelligence across all releases and scans.
            {cachedLabel && (
              <span className="ml-2 text-xs text-slate-400">{cachedLabel}</span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => fetchData(undefined, true)}
            disabled={refreshing}
            className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-60"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
          <button
            onClick={() => setShowShare(true)}
            className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-indigo-700"
          >
            <Share2 className="h-3.5 w-3.5" />
            Share Analytics
          </button>
        </div>
      </div>

      {/* ── Row 1 — KPI cards ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Total Releases Scanned"
          value={agg ? agg.total_releases_scanned.toLocaleString() : "—"}
          accent="indigo"
        />
        <StatCard
          label="Total Issues Found"
          value={agg ? agg.total_issues_found.toLocaleString() : "—"}
          accent="red"
          sub="All time, all layers"
        />
        <StatCard
          label="Issues Resolved"
          value={agg ? agg.issues_resolved.toLocaleString() : "—"}
          accent="green"
          sub={
            agg
              ? `${Math.round((agg.issues_resolved / Math.max(agg.total_issues_found, 1)) * 100)}% of all issues`
              : undefined
          }
        />
        <StatCard
          label="False Positive Rate"
          value={agg ? `${agg.false_positive_rate.toFixed(1)}%` : "—"}
          accent="amber"
          sub="Resolved without code changes"
        />
      </div>

      {/* ── Row 2 — Top Issues horizontal bar chart ────────────────────────── */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Top Failing Rules</h2>
            <p className="mt-0.5 text-xs text-slate-400">
              Most common failures across all releases · color-coded by severity
            </p>
          </div>
          <div className="flex items-center gap-3">
            {["critical", "warning", "info"].map((s) => (
              <span key={s} className="flex items-center gap-1.5 text-xs text-slate-500 capitalize">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-sm"
                  style={{ background: SEV_COLOR[s] }}
                />
                {s}
              </span>
            ))}
          </div>
        </div>

        {barData.length === 0 ? (
          <div className="flex items-center justify-center py-16 text-sm text-slate-400">
            No scan data yet — run your first scan to populate this chart.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={barData.length * 40 + 16}>
            <BarChart
              data={barData}
              layout="vertical"
              margin={{ top: 0, right: 24, left: 8, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
              <XAxis
                type="number"
                tick={{ fontSize: 11, fill: "#94a3b8" }}
                tickLine={false}
                axisLine={false}
                allowDecimals={false}
              />
              <YAxis
                type="category"
                dataKey="label"
                width={220}
                tick={{ fontSize: 11, fill: "#475569" }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const d = payload[0].payload;
                  return (
                    <div className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs shadow-xl">
                      <p className="mb-1.5 font-mono text-slate-300">{d.rule_id}</p>
                      <p className="text-slate-400">
                        Layer: <span className="font-medium text-slate-200 capitalize">{d.layer}</span>
                      </p>
                      <p className="text-slate-400">
                        Severity: <span className="font-medium capitalize" style={{ color: SEV_COLOR[d.severity] }}>{d.severity}</span>
                      </p>
                      <p className="mt-1 font-semibold text-white tabular-nums">
                        {d.occurrences.toLocaleString()} occurrences
                      </p>
                    </div>
                  );
                }}
              />
              <Bar dataKey="occurrences" radius={[0, 4, 4, 0]} maxBarSize={28}>
                {barData.map((entry, i) => (
                  <Cell
                    key={i}
                    fill={SEV_COLOR[entry.severity] ?? "#6366f1"}
                    fillOpacity={0.85}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ── Row 3 — DSP Readiness Matrix ──────────────────────────────────── */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-6 py-4">
          <h2 className="text-sm font-semibold text-slate-900">DSP Readiness Matrix</h2>
          <p className="mt-0.5 text-xs text-slate-400">
            Pass rates and failure patterns per distribution platform · current calendar month
          </p>
        </div>

        {dspMatrix.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-sm text-slate-400">
            No DSP-targeted findings yet.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100">
                  {["Platform", "Pass Rate", "vs Last Month", "Scans", "Top Failure Reasons"].map((h) => (
                    <th
                      key={h}
                      className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {dspMatrix.map((row) => {
                  const passColor =
                    row.avg_pass_rate >= 80
                      ? "text-emerald-600"
                      : row.avg_pass_rate >= 60
                      ? "text-amber-600"
                      : "text-red-600";
                  return (
                    <tr key={row.dsp} className="hover:bg-slate-50/60">
                      <td className="px-6 py-4 font-semibold text-slate-800">
                        {DSP_LABELS[row.dsp] ?? row.dsp}
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-100">
                            <div
                              className="h-full rounded-full bg-current transition-all"
                              style={{
                                width: `${row.avg_pass_rate}%`,
                                color: row.avg_pass_rate >= 80 ? "#059669" : row.avg_pass_rate >= 60 ? "#d97706" : "#dc2626",
                              }}
                            />
                          </div>
                          <span className={cn("tabular-nums font-semibold text-sm", passColor)}>
                            {row.avg_pass_rate.toFixed(1)}%
                          </span>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <TrendPill value={row.trend} />
                      </td>
                      <td className="px-6 py-4 tabular-nums text-slate-500">
                        {row.total_scans.toLocaleString()}
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex flex-wrap gap-1">
                          {row.top_failures.length === 0 ? (
                            <span className="text-xs text-slate-300">None</span>
                          ) : (
                            row.top_failures.map((r) => (
                              <span
                                key={r}
                                className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-600"
                              >
                                {r.split(".").slice(-1)[0].replaceAll("_", " ")}
                              </span>
                            ))
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Row 4 — Fraud + Layer breakdown ───────────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Fraud Signal Tracker */}
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center gap-3 border-b border-slate-100 px-6 py-4">
            <ShieldAlert className="h-4 w-4 text-red-500" />
            <div>
              <h2 className="text-sm font-semibold text-slate-900">Fraud Signal Tracker</h2>
              <p className="text-xs text-slate-400">This calendar month</p>
            </div>
          </div>

          {!fraud || fraud.total_flags_this_month === 0 ? (
            <div className="flex items-center justify-center py-12 text-sm text-slate-400">
              No fraud signals raised this month.
            </div>
          ) : (
            <div className="p-6 space-y-5">
              {/* Summary row */}
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: "Flags Raised", value: fraud.total_flags_this_month, color: "text-slate-900" },
                  { label: "Confirmed",    value: fraud.confirmed,              color: "text-red-600"   },
                  { label: "Dismissed",    value: fraud.dismissed,              color: "text-slate-400" },
                ].map(({ label, value, color }) => (
                  <div key={label} className="text-center">
                    <p className={cn("text-2xl font-bold tabular-nums", color)}>{value}</p>
                    <p className="mt-0.5 text-xs text-slate-400">{label}</p>
                  </div>
                ))}
              </div>

              {/* Confirmation rate bar */}
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-500">Confirmation Rate</span>
                  <span className="text-xs font-bold text-slate-700 tabular-nums">
                    {fraud.confirmation_rate.toFixed(1)}%
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-red-500 transition-all"
                    style={{ width: `${fraud.confirmation_rate}%` }}
                  />
                </div>
                <p className="mt-1 text-xs text-slate-400">
                  Percentage of flagged releases confirmed as actual fraud
                </p>
              </div>

              {/* Signal breakdown */}
              <div className="space-y-2">
                {fraud.by_type.map((sig) => (
                  <div key={sig.rule_id} className="flex items-center justify-between">
                    <span className="text-xs font-medium text-slate-600">{sig.signal}</span>
                    <div className="flex items-center gap-3">
                      <div className="h-1 w-20 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className="h-full rounded-full bg-red-400"
                          style={{
                            width: `${Math.min(100, (sig.total_flags / (fraud.total_flags_this_month || 1)) * 100)}%`,
                          }}
                        />
                      </div>
                      <span className="w-6 text-right text-xs font-semibold tabular-nums text-slate-700">
                        {sig.total_flags}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Layer issue distribution (donut-style bars) */}
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 px-6 py-4">
            <h2 className="text-sm font-semibold text-slate-900">Issues by Layer</h2>
            <p className="mt-0.5 text-xs text-slate-400">Distribution across QA layers · all time</p>
          </div>
          <div className="p-6 space-y-4">
            {Object.entries(
              topIssues.reduce<Record<string, number>>((acc, t) => {
                acc[t.layer] = (acc[t.layer] ?? 0) + t.occurrences;
                return acc;
              }, {})
            )
              .sort(([, a], [, b]) => b - a)
              .map(([layer, count]) => {
                const total = topIssues.reduce((s, t) => s + t.occurrences, 0);
                const pct   = total > 0 ? Math.round((count / total) * 100) : 0;
                return (
                  <div key={layer}>
                    <div className="mb-1.5 flex items-center justify-between">
                      <span className="flex items-center gap-2 text-xs font-medium capitalize text-slate-700">
                        <span
                          className="inline-block h-2 w-2 rounded-full"
                          style={{ background: LAYER_COLOR[layer] ?? "#94a3b8" }}
                        />
                        {layer}
                      </span>
                      <span className="text-xs tabular-nums text-slate-500">
                        {count.toLocaleString()} · {pct}%
                      </span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${pct}%`,
                          background: LAYER_COLOR[layer] ?? "#94a3b8",
                        }}
                      />
                    </div>
                  </div>
                );
              })}

            {topIssues.length === 0 && (
              <div className="flex items-center justify-center py-8 text-sm text-slate-400">
                No data yet.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Row 5 — Release Velocity ───────────────────────────────────────── */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Release Velocity</h2>
            <p className="mt-0.5 text-xs text-slate-400">
              Scans per week over the last 12 weeks — product adoption signal
            </p>
          </div>
        </div>

        {velocity.length === 0 ? (
          <div className="flex items-center justify-center py-16 text-sm text-slate-400">
            No scan history yet.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart
              data={velocity}
              margin={{ top: 4, right: 8, left: -16, bottom: 0 }}
            >
              <defs>
                <linearGradient id="velGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#6366f1" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0}   />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis
                dataKey="week"
                tick={{ fontSize: 11, fill: "#94a3b8" }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v) =>
                  new Date(v).toLocaleDateString("en-US", { month: "short", day: "numeric" })
                }
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#94a3b8" }}
                tickLine={false}
                axisLine={false}
                allowDecimals={false}
              />
              <Tooltip content={<DarkTooltip />} />
              <Line
                type="monotone"
                dataKey="scans"
                name="Scans"
                stroke="#6366f1"
                strokeWidth={2.5}
                dot={{ r: 3, fill: "#6366f1", strokeWidth: 0 }}
                activeDot={{ r: 5 }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ── Share modal ────────────────────────────────────────────────────── */}
      {showShare && (
        <ShareModal token={token} onClose={() => setShowShare(false)} />
      )}
    </div>
  );
}
