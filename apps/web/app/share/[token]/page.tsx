"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
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
} from "recharts";
import {
  Zap,
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  ShieldAlert,
  Loader2,
  ExternalLink,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getSharedAnalytics, type AnalyticsOverview } from "@/lib/api";

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

// ─── Helpers ──────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</p>
      <p className="mt-2 text-3xl font-bold tabular-nums text-slate-900">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

function TrendPill({ value }: { value: number }) {
  if (Math.abs(value) < 0.1)
    return (
      <span className="inline-flex items-center gap-0.5 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
        <Minus className="h-3 w-3" />0.0pp
      </span>
    );
  const up = value > 0;
  return (
    <span className={cn("inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-xs font-semibold",
      up ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"
    )}>
      {up ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
      {up ? "+" : ""}{value.toFixed(1)}pp
    </span>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function SharedAnalyticsPage() {
  const params = useParams<{ token: string }>();
  const [data, setData] = useState<AnalyticsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(false);

  useEffect(() => {
    getSharedAnalytics(params.token)
      .then(setData)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [params.token]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-50 p-8 text-center">
        <AlertTriangle className="h-10 w-10 text-amber-400" />
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Link expired or not found</h1>
          <p className="mt-1 text-sm text-slate-500">
            Share links are valid for 7 days. Ask the sender to generate a new link.
          </p>
        </div>
      </div>
    );
  }

  const agg       = data.aggregate;
  const topIssues = data.top_issues ?? [];
  const dspMatrix = data.dsp_matrix ?? [];
  const fraud     = data.fraud_signals;
  const velocity  = data.velocity ?? [];
  const dataAsOf  = data.data_as_of ?? data.cached_at;

  const barData = topIssues.map((t) => ({
    ...t,
    label: t.rule_label.length > 28 ? t.rule_label.slice(0, 26) + "…" : t.rule_label,
  }));

  return (
    <div className="min-h-screen bg-slate-50">
      {/* ── Topbar ──────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur-sm">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-indigo-600" />
            <span className="text-base font-semibold text-slate-900">SONGGATE</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
              Analytics · Read-only
            </span>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-400">
            <span>Data as of {new Date(dataAsOf).toLocaleString()}</span>
            <a
              href="https://songgate.io"
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 font-medium text-indigo-600 hover:text-indigo-700"
            >
              songgate.io <ExternalLink className="h-3 w-3" />
            </a>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-8 px-6 py-8">
        {/* ── Disclosure banner ─────────────────────────────────────────────── */}
        <div className="rounded-lg border border-indigo-100 bg-indigo-50 px-5 py-3.5 text-sm text-indigo-800">
          <strong>Anonymized data snapshot.</strong> This report contains aggregate statistics only.
          No client names, release titles, or organization identifiers are included.
        </div>

        {/* ── KPI row ───────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <KpiCard label="Releases Scanned" value={agg.total_releases_scanned.toLocaleString()} />
          <KpiCard label="Total Issues Found" value={agg.total_issues_found.toLocaleString()} sub="All QA layers" />
          <KpiCard label="Issues Resolved" value={agg.issues_resolved.toLocaleString()} />
          <KpiCard
            label="False Positive Rate"
            value={`${agg.false_positive_rate.toFixed(1)}%`}
            sub="Resolved w/o code changes"
          />
        </div>

        {/* ── Top issues bar chart ───────────────────────────────────────────── */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-5 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-slate-900">Most Common Failures</h2>
              <p className="mt-0.5 text-xs text-slate-400">Top 10 failing rules · color by severity</p>
            </div>
            <div className="flex items-center gap-3">
              {["critical", "warning", "info"].map((s) => (
                <span key={s} className="flex items-center gap-1.5 text-xs text-slate-500 capitalize">
                  <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SEV_COLOR[s] }} />
                  {s}
                </span>
              ))}
            </div>
          </div>

          {barData.length === 0 ? (
            <div className="py-12 text-center text-sm text-slate-400">No data available.</div>
          ) : (
            <ResponsiveContainer width="100%" height={barData.length * 40 + 16}>
              <BarChart data={barData} layout="vertical" margin={{ top: 0, right: 24, left: 8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} allowDecimals={false} />
                <YAxis type="category" dataKey="label" width={220} tick={{ fontSize: 11, fill: "#475569" }} tickLine={false} axisLine={false} />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const d = payload[0].payload;
                    return (
                      <div className="rounded-lg bg-slate-900 px-3 py-2 text-xs shadow-xl">
                        <p className="mb-1 font-mono text-slate-300">{d.rule_id}</p>
                        <p className="font-semibold text-white tabular-nums">{d.occurrences.toLocaleString()} occurrences</p>
                      </div>
                    );
                  }}
                />
                <Bar dataKey="occurrences" radius={[0, 4, 4, 0]} maxBarSize={28}>
                  {barData.map((entry, i) => (
                    <Cell key={i} fill={SEV_COLOR[entry.severity] ?? "#6366f1"} fillOpacity={0.85} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* ── DSP matrix ────────────────────────────────────────────────────── */}
        {dspMatrix.length > 0 && (
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-100 px-6 py-4">
              <h2 className="text-sm font-semibold text-slate-900">DSP Readiness Matrix</h2>
              <p className="mt-0.5 text-xs text-slate-400">Current month pass rates by distribution platform</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100">
                    {["Platform", "Pass Rate", "vs Last Month", "Scans"].map((h) => (
                      <th key={h} className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {dspMatrix.map((row) => {
                    const passColor = row.avg_pass_rate >= 80 ? "text-emerald-600" : row.avg_pass_rate >= 60 ? "text-amber-600" : "text-red-600";
                    return (
                      <tr key={row.dsp} className="hover:bg-slate-50/60">
                        <td className="px-6 py-3 font-semibold text-slate-800">{DSP_LABELS[row.dsp] ?? row.dsp}</td>
                        <td className="px-6 py-3">
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-100">
                              <div
                                className="h-full rounded-full transition-all"
                                style={{
                                  width: `${row.avg_pass_rate}%`,
                                  background: row.avg_pass_rate >= 80 ? "#059669" : row.avg_pass_rate >= 60 ? "#d97706" : "#dc2626",
                                }}
                              />
                            </div>
                            <span className={cn("font-semibold tabular-nums", passColor)}>
                              {row.avg_pass_rate.toFixed(1)}%
                            </span>
                          </div>
                        </td>
                        <td className="px-6 py-3"><TrendPill value={row.trend} /></td>
                        <td className="px-6 py-3 tabular-nums text-slate-500">{row.total_scans.toLocaleString()}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── Two-column: fraud + layer breakdown ───────────────────────────── */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Fraud signals */}
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="flex items-center gap-3 border-b border-slate-100 px-6 py-4">
              <ShieldAlert className="h-4 w-4 text-red-500" />
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Fraud Signal Tracker</h2>
                <p className="text-xs text-slate-400">This calendar month</p>
              </div>
            </div>
            <div className="p-6">
              {!fraud || fraud.total_flags_this_month === 0 ? (
                <p className="text-center text-sm text-slate-400 py-6">No fraud signals this month.</p>
              ) : (
                <div className="space-y-4">
                  <div className="grid grid-cols-3 gap-2 text-center">
                    {[
                      { label: "Flags", value: fraud.total_flags_this_month, cls: "text-slate-900" },
                      { label: "Confirmed", value: fraud.confirmed, cls: "text-red-600" },
                      { label: "Dismissed", value: fraud.dismissed, cls: "text-slate-400" },
                    ].map(({ label, value, cls }) => (
                      <div key={label}>
                        <p className={cn("text-xl font-bold tabular-nums", cls)}>{value}</p>
                        <p className="text-xs text-slate-400">{label}</p>
                      </div>
                    ))}
                  </div>
                  <div>
                    <div className="mb-1 flex justify-between text-xs">
                      <span className="text-slate-500">Confirmation Rate</span>
                      <span className="font-semibold text-slate-700">{fraud.confirmation_rate.toFixed(1)}%</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                      <div className="h-full rounded-full bg-red-500" style={{ width: `${fraud.confirmation_rate}%` }} />
                    </div>
                  </div>
                  <div className="space-y-2">
                    {fraud.by_type.map((sig) => (
                      <div key={sig.rule_id} className="flex items-center justify-between">
                        <span className="text-xs text-slate-600">{sig.signal}</span>
                        <span className="text-xs font-semibold tabular-nums text-slate-700">{sig.total_flags}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Issues by layer */}
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-100 px-6 py-4">
              <h2 className="text-sm font-semibold text-slate-900">Issues by Layer</h2>
              <p className="mt-0.5 text-xs text-slate-400">Distribution across QA layers</p>
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
                          <span className="inline-block h-2 w-2 rounded-full" style={{ background: LAYER_COLOR[layer] ?? "#94a3b8" }} />
                          {layer}
                        </span>
                        <span className="text-xs tabular-nums text-slate-500">{count.toLocaleString()} · {pct}%</span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{ width: `${pct}%`, background: LAYER_COLOR[layer] ?? "#94a3b8" }}
                        />
                      </div>
                    </div>
                  );
                })}
            </div>
          </div>
        </div>

        {/* ── Velocity chart ────────────────────────────────────────────────── */}
        {velocity.length > 0 && (
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="mb-5">
              <h2 className="text-sm font-semibold text-slate-900">Release Velocity</h2>
              <p className="mt-0.5 text-xs text-slate-400">Scans per week · last 12 weeks</p>
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={velocity} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis
                  dataKey="week"
                  tick={{ fontSize: 11, fill: "#94a3b8" }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => new Date(v).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                />
                <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null;
                    return (
                      <div className="rounded-lg bg-slate-900 px-3 py-2 text-xs shadow-xl">
                        <p className="text-slate-400">{new Date(label).toLocaleDateString("en-US", { month: "long", day: "numeric" })}</p>
                        <p className="font-semibold text-white">{payload[0].value} scans</p>
                      </div>
                    );
                  }}
                />
                <Line type="monotone" dataKey="scans" stroke="#6366f1" strokeWidth={2.5} dot={{ r: 3, fill: "#6366f1", strokeWidth: 0 }} activeDot={{ r: 5 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* ── Footer ────────────────────────────────────────────────────────── */}
        <footer className="border-t border-slate-200 pt-6 pb-12 text-center">
          <div className="flex items-center justify-center gap-1.5 text-sm text-slate-500">
            <Zap className="h-4 w-4 text-indigo-500" />
            <span>Powered by</span>
            <a href="https://songgate.io" target="_blank" rel="noreferrer" className="font-semibold text-indigo-600 hover:text-indigo-700">
              SONGGATE
            </a>
            <span>— Release Ops QA Autopilot</span>
          </div>
          <p className="mt-2 text-xs text-slate-400">
            This is an anonymized data snapshot. No client-identifying information is included.
          </p>
        </footer>
      </main>
    </div>
  );
}
