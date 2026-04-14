"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { useDropzone } from "react-dropzone";
import { Upload, FileText, ChevronRight, ChevronLeft, Check, Loader2, Music, FileCode2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { createRelease, createScan } from "@/lib/api";

// ─── DSP options ─────────────────────────────────────────────────────────────
const DSPS = [
  { id: "spotify", label: "Spotify", color: "bg-emerald-500" },
  { id: "apple", label: "Apple Music", color: "bg-rose-500" },
  { id: "youtube", label: "YouTube Music", color: "bg-red-500" },
  { id: "amazon", label: "Amazon Music", color: "bg-amber-500" },
  { id: "tiktok", label: "TikTok", color: "bg-slate-900" },
];

const LAYERS = [
  { id: "ddex", label: "DDEX / Format validation", desc: "Schema, required elements, ISRC format" },
  { id: "metadata", label: "DSP metadata rules", desc: "Publisher, artwork specs, copyright lines" },
  { id: "fraud", label: "Fraud pre-screening", desc: "Artist similarity, velocity, AI indicators" },
  { id: "audio", label: "Audio QA", desc: "Loudness, true peak, sample rate, clipping" },
  { id: "artwork", label: "Artwork validation", desc: "Resolution, color space, format, DPI" },
  { id: "enrichment", label: "MusicBrainz enrichment", desc: "Composer, ISWC, label suggestions" },
];

const FORMAT_OPTIONS = [
  { value: "DDEX_ERN_43", label: "DDEX ERN 4.3", icon: FileCode2 },
  { value: "DDEX_ERN_42", label: "DDEX ERN 4.2", icon: FileCode2 },
  { value: "CSV", label: "CSV", icon: FileText },
  { value: "JSON", label: "JSON", icon: FileText },
];

type Step = 0 | 1 | 2;

interface FormState {
  title: string;
  artist: string;
  upc: string;
  releaseDate: string;
  format: string;
  file: File | null;
  inputMode: "upload" | "manual";
  dsps: string[];
  layers: string[];
}

function StepIndicator({ step }: { step: Step }) {
  const steps = ["Upload", "Configure", "Running"];
  return (
    <div className="flex items-center gap-3">
      {steps.map((s, i) => (
        <div key={s} className="flex items-center gap-2">
          {i > 0 && <div className={cn("h-px w-8", i <= step ? "bg-indigo-600" : "bg-slate-200")} />}
          <div
            className={cn(
              "flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold",
              i < step
                ? "bg-indigo-600 text-white"
                : i === step
                ? "bg-indigo-600 text-white ring-2 ring-indigo-200"
                : "bg-slate-100 text-slate-400"
            )}
          >
            {i < step ? <Check className="h-3.5 w-3.5" /> : i + 1}
          </div>
          <span
            className={cn(
              "text-sm font-medium",
              i === step ? "text-slate-900" : "text-slate-400"
            )}
          >
            {s}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function NewScanPage() {
  const router = useRouter();
  const { getToken } = useAuth();
  const [step, setStep] = useState<Step>(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scanId, setScanId] = useState<string | null>(null);
  const [layerProgress, setLayerProgress] = useState<Record<string, "pending" | "running" | "done">>({});

  const [form, setForm] = useState<FormState>({
    title: "",
    artist: "",
    upc: "",
    releaseDate: "",
    format: "DDEX_ERN_43",
    file: null,
    inputMode: "upload",
    dsps: DSPS.map((d) => d.id),
    layers: LAYERS.map((l) => l.id),
  });

  // ── File dropzone ────────────────────────────────────────────────────────
  const onDrop = useCallback((accepted: File[]) => {
    if (accepted[0]) setForm((f) => ({ ...f, file: accepted[0] }));
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/zip": [".zip"],
      "text/xml": [".xml"],
      "text/csv": [".csv"],
      "application/json": [".json"],
    },
    maxFiles: 1,
  });

  // ── S3 upload helpers ────────────────────────────────────────────────────
  async function uploadFileToS3(
    file: File,
    releaseId: string,
    token: string
  ): Promise<string> {
    const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

    // 1. Get presigned PUT URL
    const presignRes = await fetch(`${API}/uploads/presign`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        release_id: releaseId,
        file_type: "ddex_package",
      }),
    });
    if (!presignRes.ok) {
      const d = await presignRes.json().catch(() => ({}));
      throw new Error(d.detail ?? "Failed to get upload URL");
    }
    const { upload_url, object_key } = await presignRes.json();

    // 2. PUT directly to S3
    const putRes = await fetch(upload_url, {
      method: "PUT",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    if (!putRes.ok) throw new Error("File upload to S3 failed");

    // 3. Confirm upload — this creates the scan automatically
    const confirmRes = await fetch(`${API}/uploads/confirm`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ object_key, release_id: releaseId, file_type: "ddex_package" }),
    });
    if (!confirmRes.ok) {
      const d = await confirmRes.json().catch(() => ({}));
      throw new Error(d.detail ?? "Upload confirmation failed");
    }
    const confirmed = await confirmRes.json();
    return confirmed.scan_id as string;
  }

  // ── Submit & run scan ────────────────────────────────────────────────────
  async function handleRunScan() {
    setSubmitting(true);
    setError(null);
    setStep(2);

    // Animate layer progress
    const layers = form.layers;
    const delays = layers.map((_, i) => i * 1200);
    for (let i = 0; i < layers.length; i++) {
      const layerId = layers[i];
      setTimeout(() => setLayerProgress((p) => ({ ...p, [layerId]: "running" })), delays[i]);
      setTimeout(() => setLayerProgress((p) => ({ ...p, [layerId]: "done" })), delays[i] + 900);
    }

    try {
      const token = await getToken();
      if (!token) throw new Error("Not authenticated");

      // 1. Create the release record
      const release = await createRelease(
        {
          title: form.title,
          artist: form.artist,
          submission_format: form.format,
          upc: form.upc || undefined,
          release_date: form.releaseDate || undefined,
        },
        token
      );

      let scanIdToUse: string;

      if (form.inputMode === "upload" && form.file) {
        // 2a. Upload file to S3 — confirm endpoint creates the scan
        scanIdToUse = await uploadFileToS3(form.file, release.id, token);
      } else {
        // 2b. Manual entry — trigger scan directly
        const scan = await createScan(release.id, token, {
          dsps: form.dsps,
          layers: form.layers,
        });
        scanIdToUse = scan.id;
      }

      setScanId(scanIdToUse);

      // 3. Poll until complete then redirect
      await pollUntilComplete(scanIdToUse, token);
      router.push(`/scans/${scanIdToUse}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "An error occurred");
      setStep(1);
    } finally {
      setSubmitting(false);
    }
  }

  async function pollUntilComplete(id: string, token: string) {
    const { getScan } = await import("@/lib/api");
    for (let attempt = 0; attempt < 60; attempt++) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const scan = await getScan(id, token);
        if (scan.status === "complete" || scan.status === "failed") return;
      } catch {
        /* keep polling */
      }
    }
  }

  const toggleDsp = (id: string) => {
    setForm((f) => ({
      ...f,
      dsps: f.dsps.includes(id) ? f.dsps.filter((d) => d !== id) : [...f.dsps, id],
    }));
  };

  const toggleLayer = (id: string) => {
    setForm((f) => ({
      ...f,
      layers: f.layers.includes(id) ? f.layers.filter((l) => l !== id) : [...f.layers, id],
    }));
  };

  const step0Valid = form.title && form.artist && (form.inputMode === "manual" || form.file);

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">New Scan</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Upload a release package and run the full 5-layer QA pipeline.
        </p>
      </div>

      <StepIndicator step={step} />

      {/* ── Step 0: Upload ─────────────────────────────────────────────── */}
      {step === 0 && (
        <div className="space-y-6">
          {/* Input mode toggle */}
          <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-1">
            {(["upload", "manual"] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setForm((f) => ({ ...f, inputMode: mode }))}
                className={cn(
                  "flex-1 rounded-md py-2 text-sm font-medium transition-colors",
                  form.inputMode === mode
                    ? "bg-white shadow-sm text-slate-900"
                    : "text-slate-500 hover:text-slate-700"
                )}
              >
                {mode === "upload" ? "Upload Package" : "Manual Entry"}
              </button>
            ))}
          </div>

          {form.inputMode === "upload" && (
            <div>
              {/* Format selector */}
              <div className="mb-4 grid grid-cols-4 gap-2">
                {FORMAT_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => setForm((f) => ({ ...f, format: opt.value }))}
                    className={cn(
                      "flex flex-col items-center gap-1.5 rounded-lg border p-3 text-center text-xs font-medium transition-colors",
                      form.format === opt.value
                        ? "border-indigo-300 bg-indigo-50 text-indigo-700"
                        : "border-slate-200 bg-white text-slate-500 hover:border-slate-300 hover:bg-slate-50"
                    )}
                  >
                    <opt.icon className="h-5 w-5" />
                    {opt.label}
                  </button>
                ))}
              </div>

              {/* Dropzone */}
              <div
                {...getRootProps()}
                className={cn(
                  "cursor-pointer rounded-xl border-2 border-dashed p-12 text-center transition-colors",
                  isDragActive
                    ? "border-indigo-400 bg-indigo-50"
                    : form.file
                    ? "border-emerald-300 bg-emerald-50"
                    : "border-slate-200 bg-slate-50 hover:border-slate-300 hover:bg-white"
                )}
              >
                <input {...getInputProps()} />
                {form.file ? (
                  <div className="flex flex-col items-center gap-2">
                    <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100">
                      <Check className="h-6 w-6 text-emerald-600" />
                    </div>
                    <p className="text-sm font-medium text-emerald-700">{form.file.name}</p>
                    <p className="text-xs text-slate-400">
                      {(form.file.size / 1024 / 1024).toFixed(2)} MB — click to replace
                    </p>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-3">
                    <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100">
                      <Upload className="h-6 w-6 text-slate-400" />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-slate-700">
                        Drop your DDEX package here, or{" "}
                        <span className="text-indigo-600">browse</span>
                      </p>
                      <p className="mt-0.5 text-xs text-slate-400">
                        ZIP, XML, CSV, or JSON — max 50 MB
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Release metadata fields */}
          <div className="rounded-lg border border-slate-200 bg-white p-5 space-y-4">
            <h3 className="text-sm font-semibold text-slate-800">Release Details</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-600">
                  Release Title <span className="text-red-500">*</span>
                </label>
                <input
                  value={form.title}
                  onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                  placeholder="e.g. Midnight Drive"
                  className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-600">
                  Artist Name <span className="text-red-500">*</span>
                </label>
                <input
                  value={form.artist}
                  onChange={(e) => setForm((f) => ({ ...f, artist: e.target.value }))}
                  placeholder="e.g. The Band"
                  className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-600">UPC</label>
                <input
                  value={form.upc}
                  onChange={(e) => setForm((f) => ({ ...f, upc: e.target.value }))}
                  placeholder="e.g. 012345678901"
                  className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-600">Release Date</label>
                <input
                  type="date"
                  value={form.releaseDate}
                  onChange={(e) => setForm((f) => ({ ...f, releaseDate: e.target.value }))}
                  className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                />
              </div>
            </div>
          </div>

          <div className="flex justify-end">
            <button
              onClick={() => setStep(1)}
              disabled={!step0Valid}
              className="flex items-center gap-2 rounded-md bg-indigo-600 px-5 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Configure <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* ── Step 1: Configure ──────────────────────────────────────────── */}
      {step === 1 && (
        <div className="space-y-6">
          {/* DSP selection */}
          <div className="rounded-lg border border-slate-200 bg-white p-5">
            <h3 className="mb-3 text-sm font-semibold text-slate-800">Target DSPs</h3>
            <p className="mb-4 text-xs text-slate-400">
              Select the platforms to validate against. Rules are filtered per DSP.
            </p>
            <div className="grid grid-cols-5 gap-2">
              {DSPS.map((dsp) => {
                const active = form.dsps.includes(dsp.id);
                return (
                  <button
                    key={dsp.id}
                    onClick={() => toggleDsp(dsp.id)}
                    className={cn(
                      "flex flex-col items-center gap-2 rounded-lg border p-3 text-xs font-medium transition-colors",
                      active
                        ? "border-indigo-200 bg-indigo-50 text-indigo-700"
                        : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                    )}
                  >
                    <span className={cn("h-3 w-3 rounded-full", dsp.color)} />
                    {dsp.label}
                    {active && <Check className="h-3 w-3 text-indigo-600" />}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Layer selection */}
          <div className="rounded-lg border border-slate-200 bg-white p-5">
            <h3 className="mb-3 text-sm font-semibold text-slate-800">Scan Layers</h3>
            <p className="mb-4 text-xs text-slate-400">
              Choose which QA layers to run. Audio and enrichment add latency.
            </p>
            <div className="space-y-2">
              {LAYERS.map((layer) => {
                const active = form.layers.includes(layer.id);
                return (
                  <label
                    key={layer.id}
                    className={cn(
                      "flex cursor-pointer items-start gap-3 rounded-lg border p-3.5 transition-colors",
                      active ? "border-indigo-200 bg-indigo-50/50" : "border-slate-100 bg-slate-50/50 hover:border-slate-200"
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={active}
                      onChange={() => toggleLayer(layer.id)}
                      className="mt-0.5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                    />
                    <div>
                      <p className="text-sm font-medium text-slate-800">{layer.label}</p>
                      <p className="text-xs text-slate-400">{layer.desc}</p>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>

          {error && (
            <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <div className="flex items-center justify-between">
            <button
              onClick={() => setStep(0)}
              className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
            >
              <ChevronLeft className="h-4 w-4" /> Back
            </button>
            <button
              onClick={handleRunScan}
              disabled={submitting || form.dsps.length === 0 || form.layers.length === 0}
              className="flex items-center gap-2 rounded-md bg-indigo-600 px-6 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50"
            >
              {submitting ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Starting scan…</>
              ) : (
                <>Run Scan <Music className="h-4 w-4" /></>
              )}
            </button>
          </div>
        </div>
      )}

      {/* ── Step 2: Running ───────────────────────────────────────────── */}
      {step === 2 && (
        <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
          <div className="mb-8 flex flex-col items-center text-center">
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-indigo-100">
              <Loader2 className="h-8 w-8 animate-spin text-indigo-600" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900">Scan in Progress</h2>
            <p className="mt-1 text-sm text-slate-500">
              Running all QA layers — this usually takes 15–30 seconds.
            </p>
            {scanId && (
              <p className="mt-2 font-mono text-xs text-slate-400">
                Scan ID: {scanId.slice(0, 8)}…
              </p>
            )}
          </div>

          <div className="space-y-3">
            {form.layers.map((layerId) => {
              const layer = LAYERS.find((l) => l.id === layerId);
              const s = layerProgress[layerId] ?? "pending";
              return (
                <div key={layerId} className="flex items-center gap-3 rounded-lg border border-slate-100 bg-slate-50/60 p-3.5">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full">
                    {s === "done" ? (
                      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-100">
                        <Check className="h-4 w-4 text-emerald-600" />
                      </div>
                    ) : s === "running" ? (
                      <Loader2 className="h-5 w-5 animate-spin text-indigo-500" />
                    ) : (
                      <div className="h-5 w-5 rounded-full border-2 border-slate-200" />
                    )}
                  </div>
                  <div className="flex-1">
                    <p className={cn("text-sm font-medium", s === "done" ? "text-slate-500" : "text-slate-800")}>
                      {layer?.label ?? layerId}
                    </p>
                    <p className="text-xs text-slate-400">{layer?.desc}</p>
                  </div>
                  <span className={cn(
                    "text-xs font-medium",
                    s === "done" ? "text-emerald-600" : s === "running" ? "text-indigo-600" : "text-slate-300"
                  )}>
                    {s === "done" ? "Done" : s === "running" ? "Running…" : "Queued"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
