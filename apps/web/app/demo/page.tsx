"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Zap,
  Upload,
  PlayCircle,
  CheckCircle2,
  AlertTriangle,
  Info,
  ArrowRight,
  Loader2,
  ShieldAlert,
  ChevronDown,
  ChevronUp,
  Lock,
  Download,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DemoResult {
  id: string;
  layer: string;
  rule_name: string;
  severity: "critical" | "error" | "warning" | "info";
  message: string;
  field_path: string | null;
  actual_value: string | null;
  fix_hint: string | null;
  dsp_targets: string[];
}

interface DemoScan {
  scan_id: string;
  demo: boolean;
  file_format: "xml" | "csv" | "json";
  watermark: string;
  status: string;
  readiness_score: number;
  grade: "PASS" | "WARN" | "FAIL";
  critical_count: number;
  warning_count: number;
  info_count: number;
  total_issues: number;
  layers_run: string[];
  results: DemoResult[];
  release_title: string;
  release_artist: string;
  completed_at: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const FORMAT_STEP_LABEL: Record<string, string> = {
  csv:  "CSV Validation",
  json: "JSON Validation",
  xml:  "DDEX Validation",
};

const FORMAT_LAYER_LABEL: Record<string, string> = {
  csv:  "CSV / Format",
  json: "JSON / Format",
  xml:  "DDEX / Format",
};

function getLayerSteps(fmt: string) {
  return [
    { key: "ddex",     label: FORMAT_STEP_LABEL[fmt] ?? "Format Validation", duration: 800 },
    { key: "metadata", label: "DSP Metadata Rules",                           duration: 900 },
    { key: "fraud",    label: "Fraud Pre-Screening",                          duration: 1100 },
    { key: "artwork",  label: "Metadata Enrichment",                          duration: 700 },
  ];
}

function getLayerLabels(fmt: string): Record<string, string> {
  return {
    ddex:     FORMAT_LAYER_LABEL[fmt] ?? "Format Validation",
    metadata: "DSP Metadata Rules",
    fraud:    "Fraud Screening",
    artwork:  "Artwork Validation",
  };
}

const SEV_ORDER: Record<string, number> = { critical: 0, error: 0, warning: 1, info: 2 };

// ── Right-click / devtools protection ─────────────────────────────────────────

function useDevtoolsProtection() {
  useEffect(() => {
    function onContextMenu(e: MouseEvent) {
      const target = e.target as HTMLElement;
      if (target.closest("[data-demo-results]")) {
        e.preventDefault();
        window.__demoProtectionAlert?.();
      }
    }
    document.addEventListener("contextmenu", onContextMenu);
    return () => document.removeEventListener("contextmenu", onContextMenu);
  }, []);
}

declare global {
  interface Window {
    __demoProtectionAlert?: () => void;
  }
}

// ── Score circle (inline, no server component dependency) ─────────────────────

function ScoreCircle({ score, grade }: { score: number; grade: "PASS" | "WARN" | "FAIL" | null }) {
  const container = 200;
  const stroke    = 12;
  const r         = 82;
  const cx        = container / 2;
  const cy        = container / 2;
  const circumference = 2 * Math.PI * r;
  const pct = score !== null ? Math.max(0, Math.min(100, score)) / 100 : 0;
  const dashoffset = circumference * (1 - pct);

  const colors = {
    PASS: { track: "#d1fae5", fill: "#10b981", text: "text-emerald-600", label: "bg-emerald-100 text-emerald-700" },
    WARN: { track: "#fef3c7", fill: "#f59e0b", text: "text-amber-600",   label: "bg-amber-100 text-amber-700" },
    FAIL: { track: "#fee2e2", fill: "#ef4444", text: "text-red-600",     label: "bg-red-100 text-red-700" },
    null: { track: "#e2e8f0", fill: "#94a3b8", text: "text-slate-400",   label: "bg-slate-100 text-slate-500" },
  }[grade ?? "null"];

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative" style={{ width: container, height: container }}>
        <svg width={container} height={container} viewBox={`0 0 ${container} ${container}`}
          style={{ transform: "rotate(-90deg)" }}>
          <circle cx={cx} cy={cy} r={r} fill="none" stroke={colors.track} strokeWidth={stroke} />
          <circle cx={cx} cy={cy} r={r} fill="none" stroke={colors.fill} strokeWidth={stroke}
            strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={dashoffset}
            style={{ transition: "stroke-dashoffset 1s cubic-bezier(0.4,0,0.2,1)" }} />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5">
          <span className={cn("text-5xl font-bold tabular-nums leading-none", colors.text)}>
            {Math.round(score)}
          </span>
          <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Score</span>
          <span className="mt-1 text-[10px] font-semibold text-slate-400 uppercase tracking-widest">DEMO</span>
        </div>
      </div>
      {grade && (
        <span className={cn("rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider", colors.label)}>
          {grade}
        </span>
      )}
    </div>
  );
}

// ── Issue card ────────────────────────────────────────────────────────────────

function IssueCard({ result }: { result: DemoResult }) {
  const [expanded, setExpanded] = useState(false);
  const isFraud = result.layer === "fraud";

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
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white transition-shadow hover:shadow-sm">
      <div className="flex cursor-pointer items-start gap-3 p-4"
        onClick={() => setExpanded(e => !e)}>
        <div className="mt-0.5 shrink-0">
          {(result.severity === "critical" || result.severity === "error")
            ? <AlertTriangle className="h-4 w-4 text-red-500" />
            : result.severity === "warning"
            ? <AlertTriangle className="h-4 w-4 text-amber-500" />
            : <Info className="h-4 w-4 text-blue-500" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-4">
            <p className="text-sm font-medium text-slate-800">{result.message}</p>
            <div className="flex shrink-0 items-center gap-2">
              <SeverityBadge severity={result.severity} />
              {expanded
                ? <ChevronUp className="h-4 w-4 text-slate-400" />
                : <ChevronDown className="h-4 w-4 text-slate-400" />}
            </div>
          </div>
          <p className="mt-0.5 text-xs text-slate-400">{result.rule_name}</p>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-slate-100 bg-slate-50 px-4 py-3 space-y-3">
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
        </div>
      )}
    </div>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const cls: Record<string, string> = {
    critical: "bg-red-100 text-red-700",
    error:    "bg-red-100 text-red-700",
    warning:  "bg-amber-100 text-amber-700",
    info:     "bg-blue-50 text-blue-700",
  };
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold capitalize",
      cls[severity] ?? "bg-slate-100 text-slate-500")}>
      {severity}
    </span>
  );
}

// ── Terms modal ───────────────────────────────────────────────────────────────

function TermsModal({ onAccept }: { onAccept: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-2xl">
        <div className="mb-5 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-indigo-100">
            <Zap className="h-5 w-5 text-indigo-600" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-slate-900">SONGGATE Demo</h2>
            <p className="text-xs text-slate-500">Evaluation access — one-time agreement</p>
          </div>
        </div>

        <p className="mb-5 text-sm leading-relaxed text-slate-600">
          By using this demo you agree not to reverse engineer, replicate, or
          redistribute SONGGATE&apos;s validation methodology. This demo is provided
          for evaluation purposes only.
        </p>

        <p className="mb-6 text-xs text-slate-400">
          © 2026 HOUSE LABS / HOUSESONHILLS. All rights reserved.
        </p>

        <button
          onClick={onAccept}
          className="w-full rounded-lg bg-indigo-600 px-4 py-3 text-sm font-semibold text-white hover:bg-indigo-700 transition-colors"
        >
          I agree — show me the demo
        </button>
      </div>
    </div>
  );
}

// ── Devtools notice ───────────────────────────────────────────────────────────

function DevtoolsNotice({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  if (!visible) return null;
  return (
    <div className="fixed bottom-6 right-6 z-50 max-w-xs rounded-xl border border-slate-200 bg-white p-4 shadow-xl">
      <div className="flex items-start gap-3">
        <Lock className="mt-0.5 h-4 w-4 shrink-0 text-indigo-500" />
        <div>
          <p className="text-xs font-semibold text-slate-800">Developer tools disabled</p>
          <p className="mt-1 text-xs text-slate-500 leading-relaxed">
            To protect our proprietary validation engine, developer tools are
            disabled in demo mode. Create an account for full API access.
          </p>
          <Link href="/sign-up" className="mt-2 inline-block text-xs font-medium text-indigo-600 hover:underline">
            Create an account →
          </Link>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xs">✕</button>
      </div>
    </div>
  );
}

// ── Progress animation ────────────────────────────────────────────────────────

function ScanProgress({ completedLayers, fmt }: { completedLayers: Set<string>; fmt: string }) {
  const steps = getLayerSteps(fmt);
  return (
    <div className="space-y-3">
      {steps.map((step, i) => {
        const done    = completedLayers.has(step.key);
        const active  = !done && i === completedLayers.size;
        return (
          <div key={step.key} className={cn(
            "flex items-center gap-3 rounded-lg border px-4 py-3 transition-all",
            done   ? "border-emerald-200 bg-emerald-50"   : "",
            active ? "border-indigo-200 bg-indigo-50"     : "",
            !done && !active ? "border-slate-100 bg-slate-50 opacity-50" : "",
          )}>
            <div className="shrink-0">
              {done
                ? <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                : active
                ? <Loader2 className="h-5 w-5 animate-spin text-indigo-500" />
                : <div className="h-5 w-5 rounded-full border-2 border-slate-200" />}
            </div>
            <span className={cn(
              "text-sm font-medium",
              done   ? "text-emerald-700" : "",
              active ? "text-indigo-700"  : "text-slate-400",
            )}>
              {step.label}
            </span>
            {done && (
              <span className="ml-auto text-xs font-semibold text-emerald-600">✓</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Layer mini bar ────────────────────────────────────────────────────────────

function layerScore(results: DemoResult[], layer: string): number {
  const layerResults = results.filter(r => r.layer === layer);
  // "error" (DDEX layer) and "critical" both count at the critical rate
  const criticals    = layerResults.filter(r => r.severity === "critical" || r.severity === "error").length;
  const warnings     = layerResults.filter(r => r.severity === "warning").length;
  // Mirror backend formula: same deduction weights and caps
  const deductions   = Math.min(criticals * 10, 60) + Math.min(warnings * 3, 25);
  return Math.max(0, 100 - deductions);
}

function LayerMiniBar({ label, score }: { label: string; score: number }) {
  const color = score >= 80 ? "bg-emerald-500" : score >= 60 ? "bg-amber-400" : "bg-red-500";
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-500">{label}</span>
        <span className="text-xs font-semibold text-slate-700 tabular-nums">{score}</span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-100">
        <div className={cn("h-1.5 rounded-full transition-all duration-700", color)}
          style={{ width: `${Math.min(100, score)}%` }} />
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

type Phase = "terms" | "hero" | "scanning" | "results";

export default function DemoPage() {
  const [phase, setPhase]         = useState<Phase>("terms");
  const [termsAccepted, setTerms] = useState(false);
  const [completedLayers, setCompleted] = useState<Set<string>>(new Set());
  const [scanResult, setScanResult]     = useState<DemoScan | null>(null);
  const [scanError, setScanError]       = useState<string | null>(null);
  const [scanFormat, setScanFormat]     = useState<string>("xml");
  const [devtoolsNotice, setDevtoolsNotice] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<{ name: string; content: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Register devtools alert
  useEffect(() => {
    window.__demoProtectionAlert = () => setDevtoolsNotice(true);
    return () => { delete window.__demoProtectionAlert; };
  }, []);

  // Check localStorage for prior terms acceptance
  useEffect(() => {
    try {
      if (localStorage.getItem("songgate_demo_terms") === "accepted") {
        setTerms(true);
        setPhase("hero");
      }
    } catch { /* incognito — ignore */ }
  }, []);

  function acceptTerms() {
    try { localStorage.setItem("songgate_demo_terms", "accepted"); } catch { /* ignore */ }
    setTerms(true);
    setPhase("hero");
  }

  // ── Animate progress layers ───────────────────────────────────────────────

  async function animateLayers(scanPromise: Promise<DemoScan>, fmt: string = "xml") {
    const completed = new Set<string>();
    setCompleted(new Set());
    setScanResult(null);
    setScanFormat(fmt);
    setPhase("scanning");

    let result: DemoScan | null = null;
    let fetchError: string | null = null;

    // Start the real scan in parallel with the animation
    scanPromise.then(r => { result = r; }).catch(e => { fetchError = e.message; });

    for (const step of getLayerSteps(fmt)) {
      await new Promise(r => setTimeout(r, step.duration));
      completed.add(step.key);
      setCompleted(new Set(completed));
    }

    // Wait a moment for results to arrive
    const maxWait = 10_000;
    const start = Date.now();
    while (!result && !fetchError && Date.now() - start < maxWait) {
      await new Promise(r => setTimeout(r, 200));
    }

    if (fetchError) {
      setScanError(fetchError);
      setPhase("hero");
      return;
    }

    if (result) {
      setScanResult(result);
      setPhase("results");
    } else {
      setScanError("Scan timed out. Please try again.");
      setPhase("hero");
    }
  }

  // ── Scan with sample release ──────────────────────────────────────────────

  async function scanSample() {
    setScanError(null);
    const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    const promise = fetch(`${API}/api/demo/scan`, { method: "POST" })
      .then(async res => {
        if (res.status === 429) {
          const d = await res.json().catch(() => ({}));
          throw new Error(d.detail?.message ?? "Rate limit reached.");
        }
        if (!res.ok) throw new Error("Scan failed. Please try again.");
        return res.json() as Promise<DemoScan>;
      });
    await animateLayers(promise, "xml");
  }

  // ── Scan with uploaded file ───────────────────────────────────────────────

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setScanError(null);

    // Detect format from filename for the loading animation
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "xml";
    const fmt = ext === "csv" ? "csv" : ext === "json" ? "json" : "xml";

    // Read and store file content for download later
    const text = await file.text();
    setUploadedFile({ name: file.name, content: text });

    const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    const fd  = new FormData();
    fd.append("file", file);

    const promise = fetch(`${API}/api/demo/scan`, { method: "POST", body: fd })
      .then(async res => {
        if (res.status === 429) {
          const d = await res.json().catch(() => ({}));
          throw new Error(d.detail?.message ?? "Rate limit reached.");
        }
        if (!res.ok) throw new Error("Scan failed. Please try again.");
        return res.json() as Promise<DemoScan>;
      });

    await animateLayers(promise, fmt);
    // Reset file input
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  // ── Download uploaded file ────────────────────────────────────────────────

  function downloadFile() {
    if (!uploadedFile) return;
    const ext  = uploadedFile.name.split(".").pop()?.toLowerCase() ?? "xml";
    const mime = ext === "json" ? "application/json" : ext === "csv" ? "text/csv" : "application/xml";
    const blob = new Blob([uploadedFile.content], { type: mime });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = uploadedFile.name;
    a.click();
    URL.revokeObjectURL(url);
  }

  // ── Demo CSV export ───────────────────────────────────────────────────────

  function exportDemoCSV() {
    if (!scanResult) return;
    const date = new Date().toISOString().slice(0, 10);
    const safe = (scanResult.release_title || "scan").replace(/[^\w-]/g, "_").slice(0, 60);
    const filename = `SONGGATE_DEMO_${safe}_${date}.csv`;
    const rows = [
      ["rule_name", "layer", "severity", "message", "fix_hint", "dsp_targets"],
      ...scanResult.results.map((r) => [
        r.rule_name,
        r.layer,
        r.severity,
        r.message,
        r.fix_hint ?? "",
        r.dsp_targets.join(","),
      ]),
    ];
    const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
  }

  // ── Demo JSON export ──────────────────────────────────────────────────────

  function exportDemoJSON() {
    if (!scanResult) return;
    const date = new Date().toISOString().slice(0, 10);
    const safe = (scanResult.release_title || "scan").replace(/[^\w-]/g, "_").slice(0, 60);
    const filename = `SONGGATE_DEMO_${safe}_${date}.json`;
    const payload = {
      ...scanResult,
      watermark: "SONGGATE Demo — Not for redistribution · songgate.io",
      exported_at: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
  }

  // ── Results grouping ──────────────────────────────────────────────────────

  function groupedResults() {
    if (!scanResult) return {};
    const groups: Record<string, DemoResult[]> = {};
    for (const r of scanResult.results) {
      (groups[r.layer] ??= []).push(r);
    }
    for (const layer of Object.keys(groups)) {
      groups[layer].sort((a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9));
    }
    return groups;
  }

  const layers = ["ddex", "metadata", "fraud", "artwork"];
  const layerLabels = getLayerLabels(scanResult?.file_format ?? scanFormat);

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-white text-slate-900">
      {/* Devtools notice */}
      <DevtoolsNotice visible={devtoolsNotice} onClose={() => setDevtoolsNotice(false)} />

      {/* Terms modal */}
      {phase === "terms" && <TermsModal onAccept={acceptTerms} />}

      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-slate-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-6">
          <Link href="/" className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-indigo-600" />
            <span className="font-semibold tracking-tight">SONGGATE</span>
          </Link>
          <div className="flex items-center gap-3">
            <span className="hidden sm:inline rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700">
              Demo Mode
            </span>
            <Link
              href="/sign-up"
              className="rounded-md bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 transition-colors"
            >
              Start free trial
            </Link>
          </div>
        </div>
      </header>

      {/* ── HERO ─────────────────────────────────────────────────────────── */}
      {(phase === "hero" || phase === "scanning") && (
        <section className="mx-auto max-w-3xl px-6 pb-20 pt-20 text-center">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700">
            <Zap className="h-3.5 w-3.5" /> Live demo — no account required
          </div>
          <h1 className="mt-4 text-4xl font-bold leading-tight tracking-tight text-slate-900 sm:text-5xl">
            See SONGGATE in action.
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-lg text-slate-500">
            Upload a release or use our sample — get your readiness score in 45 seconds.
          </p>

          {scanError && (
            <div className="mt-4 mx-auto max-w-sm rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {scanError}
            </div>
          )}

          {phase === "hero" && (
            <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
              <button
                onClick={scanSample}
                className="flex items-center gap-2 rounded-lg bg-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 transition-colors"
              >
                <PlayCircle className="h-4 w-4" />
                Scan our sample release
              </button>

              <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 px-6 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-colors">
                <Upload className="h-4 w-4" />
                Upload your file
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xml,.csv,.json"
                  className="hidden"
                  onChange={handleFileUpload}
                />
              </label>
            </div>
          )}

          <p className="mt-4 text-xs text-slate-400">
            Work with three supported formats: DDEX XML, CSV, and JSON. Your files are not stored.
          </p>

          {/* Scanning animation */}
          {phase === "scanning" && (
            <div className="mt-12 mx-auto max-w-sm">
              <p className="mb-6 text-sm font-semibold text-slate-700">
                Running your release through 5 QA layers…
              </p>
              <ScanProgress completedLayers={completedLayers} fmt={scanFormat} />
              <p className="mt-4 text-xs text-slate-400">
                Estimated time: ~45 seconds
              </p>
            </div>
          )}
        </section>
      )}

      {/* ── RESULTS ──────────────────────────────────────────────────────── */}
      {phase === "results" && scanResult && (
        <div data-demo-results>
          {/* Watermark banner */}
          <div className="border-b border-dashed border-indigo-200 bg-indigo-50 py-2 text-center text-xs font-semibold text-indigo-600 tracking-wide">
            SONGGATE Confidential Demo — Not for redistribution · songgate.io
          </div>

          <div className="mx-auto max-w-4xl space-y-8 px-6 py-10">
            {/* Header */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div>
                <h1 className="text-2xl font-semibold text-slate-900">
                  {scanResult.release_title || "Scan Results"}
                  {scanResult.release_artist && (
                    <span className="ml-2 text-lg font-normal text-slate-500">
                      — {scanResult.release_artist}
                    </span>
                  )}
                </h1>
                <p className="mt-0.5 text-xs text-slate-400">Demo scan · Results not stored</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => { setPhase("hero"); setUploadedFile(null); }}
                  className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                >
                  ← New scan
                </button>
                <button
                  onClick={exportDemoCSV}
                  className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                >
                  <Download className="h-3 w-3" />
                  CSV
                </button>
                <button
                  onClick={exportDemoJSON}
                  className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                >
                  <Download className="h-3 w-3" />
                  JSON
                </button>
                {uploadedFile ? (
                  <button
                    onClick={downloadFile}
                    className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
                  >
                    <Download className="h-3 w-3" />
                    Download file
                  </button>
                ) : (
                  <Link
                    href="/sign-up"
                    className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
                  >
                    <Lock className="h-3 w-3" />
                    Create account for PDF
                  </Link>
                )}
              </div>
            </div>

            {/* Score + breakdown */}
            <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
              <div className="flex flex-col items-center gap-10 md:flex-row md:items-start">
                <div className="shrink-0 flex flex-col items-center gap-4">
                  <ScoreCircle score={scanResult.readiness_score} grade={scanResult.grade} />
                  <div className="flex items-center gap-4 text-center">
                    <div>
                      <p className="text-2xl font-bold text-red-600 tabular-nums">{scanResult.critical_count}</p>
                      <p className="text-xs text-slate-400">Critical</p>
                    </div>
                    <div className="h-8 w-px bg-slate-100" />
                    <div>
                      <p className="text-2xl font-bold text-amber-500 tabular-nums">{scanResult.warning_count}</p>
                      <p className="text-xs text-slate-400">Warnings</p>
                    </div>
                    <div className="h-8 w-px bg-slate-100" />
                    <div>
                      <p className="text-2xl font-bold text-slate-400 tabular-nums">{scanResult.info_count}</p>
                      <p className="text-xs text-slate-400">Info</p>
                    </div>
                  </div>
                </div>

                <div className="flex-1 w-full space-y-5">
                  <div>
                    <h2 className="text-sm font-semibold text-slate-800">Score Breakdown by Layer</h2>
                    <p className="mt-0.5 text-xs text-slate-400">Demo scan — results are ephemeral and not stored.</p>
                  </div>
                  <div className="space-y-3">
                    {layers.map(layer => (
                      <LayerMiniBar
                        key={layer}
                        label={layerLabels[layer] ?? layer}
                        score={layerScore(scanResult.results, layer)}
                      />
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Issues by layer */}
            {layers.filter(l => groupedResults()[l]?.length).map(layer => {
              const results   = groupedResults()[layer] ?? [];
              const critical  = results.filter(r => r.severity === "critical" || r.severity === "error").length;
              const warnings  = results.filter(r => r.severity === "warning").length;
              return (
                <div key={layer} className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
                      {layerLabels[layer] ?? layer}
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
                    {results.map(r => <IssueCard key={r.id} result={r} />)}
                  </div>
                </div>
              );
            })}

            {/* All clear */}
            {scanResult.total_issues === 0 && (
              <div className="flex flex-col items-center justify-center rounded-xl border border-emerald-200 bg-emerald-50 py-12 text-center">
                <CheckCircle2 className="mb-3 h-10 w-10 text-emerald-500" />
                <h2 className="text-base font-semibold text-emerald-800">All checks passed</h2>
                <p className="mt-1 text-sm text-emerald-600">
                  No issues found. This release looks ready for delivery.
                </p>
              </div>
            )}

            {/* CTA */}
            <div className="rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 to-indigo-100/50 px-8 py-10 text-center">
              <h2 className="text-2xl font-bold tracking-tight text-slate-900">
                Ready to pre-flight your catalog?
              </h2>
              <p className="mx-auto mt-3 max-w-md text-sm text-slate-500">
                Used by music distributors and labels shipping releases at scale.
              </p>
              <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
                <Link
                  href="/sign-up"
                  className="flex items-center gap-2 rounded-lg bg-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 transition-colors"
                >
                  Start free trial <ArrowRight className="h-4 w-4" />
                </Link>
                <a
                  href="mailto:andrew@housesonhills.io?subject=SONGGATE Pilot&body=Hi, I'd like to book a call to discuss a SONGGATE pilot."
                  className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-6 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-colors"
                >
                  Book a pilot call
                </a>
              </div>
              <p className="mt-5 text-xs text-slate-400">
                Export PDF, full audit history, and API access — available after sign-up.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
