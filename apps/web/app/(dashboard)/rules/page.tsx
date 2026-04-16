"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

type Severity = "critical" | "warning" | "info";

interface Rule {
  id: string;
  title: string;
  description: string;
  severity: Severity;
  layer: string;
  dsp: string | null;
  fixHint?: string;
}

const RULES: Rule[] = [
  // ── Universal / Identifiers
  { id: "universal.metadata.upc_format", title: "UPC must be 12 or 13 digits", description: "The UPC/EAN barcode must consist of exactly 12 or 13 numeric digits.", severity: "critical", layer: "metadata", dsp: null, fixHint: "Obtain a valid UPC from your distributor and re-submit." },
  { id: "universal.metadata.isrc_present", title: "Every track must have an ISRC", description: "Each track must carry an ISRC. Missing ISRCs block royalty attribution.", severity: "critical", layer: "metadata", dsp: null, fixHint: "Register ISRCs at your national ISRC agency or distributor." },
  { id: "universal.metadata.isrc_format", title: "ISRC must follow ISO 3901 format", description: "Each ISRC must match CC-XXX-YY-NNNNN pattern.", severity: "critical", layer: "metadata", dsp: null, fixHint: "Correct to ISO 3901 format, e.g. US-ABC-23-00001." },
  { id: "universal.metadata.isrc_unique", title: "ISRCs must be unique across tracks", description: "Two tracks sharing the same ISRC indicate a data error.", severity: "critical", layer: "metadata", dsp: null, fixHint: "Assign a distinct ISRC to each track; do not reuse ISRCs." },
  // ── Basic metadata
  { id: "universal.metadata.release_title_required", title: "Release title is required", description: "Every release must have a non-empty title field.", severity: "critical", layer: "metadata", dsp: null },
  { id: "universal.metadata.artist_name_required", title: "Artist name is required", description: "A primary artist name must be present on the release.", severity: "critical", layer: "metadata", dsp: null },
  { id: "universal.metadata.label_required", title: "Label name is required", description: "The record label or self-release name must be present.", severity: "critical", layer: "metadata", dsp: null },
  { id: "universal.metadata.release_date_required", title: "Release date is required", description: "A release date must be specified for the submission.", severity: "critical", layer: "metadata", dsp: null, fixHint: "Provide a release date in YYYY-MM-DD format." },
  { id: "universal.metadata.genre_required", title: "Primary genre is required", description: "At least one genre must be specified for the release.", severity: "warning", layer: "metadata", dsp: null },
  // ── Copyright
  { id: "universal.metadata.c_line_required", title: "℗ copyright line required", description: "A sound-recording copyright (℗) line must be present.", severity: "critical", layer: "metadata", dsp: null },
  { id: "universal.metadata.p_line_required", title: "© publishing line required", description: "A composition/publishing copyright (©) line must be present.", severity: "critical", layer: "metadata", dsp: null },
  // ── Artwork
  { id: "universal.artwork.resolution_too_low", title: "Artwork resolution too low", description: "Cover art must be at least 3000×3000 pixels.", severity: "critical", layer: "artwork", dsp: null, fixHint: "Export artwork at 3000×3000 or higher." },
  { id: "universal.artwork.not_square", title: "Artwork must be square", description: "Cover art dimensions must be equal (1:1 aspect ratio).", severity: "critical", layer: "artwork", dsp: null },
  { id: "universal.artwork.wrong_color_mode", title: "Artwork must be RGB", description: "Cover art must be in RGB color mode, not CMYK.", severity: "critical", layer: "artwork", dsp: null, fixHint: "Convert artwork to RGB in Photoshop or equivalent." },
  // ── Audio
  { id: "universal.audio.loudness_too_loud", title: "Loudness too high", description: "Integrated loudness must not exceed −9 LUFS.", severity: "critical", layer: "audio", dsp: null, fixHint: "Apply limiting/normalization to bring loudness down." },
  { id: "universal.audio.true_peak_exceeded", title: "True peak exceeds −1 dBTP", description: "True peak level must be below −1 dBTP to prevent clipping on DSPs.", severity: "critical", layer: "audio", dsp: null },
  { id: "universal.audio.sample_rate_invalid", title: "Sample rate not supported", description: "Audio must be 44.1 kHz or 48 kHz.", severity: "critical", layer: "audio", dsp: null },
  // ── DDEX
  { id: "ddex.schema_invalid", title: "DDEX schema validation failed", description: "The ERN XML file does not conform to the declared schema version.", severity: "critical", layer: "ddex", dsp: null, fixHint: "Validate your DDEX file against the ERN 4.x XSD before submitting." },
  { id: "ddex.missing_required_element", title: "Missing required DDEX element", description: "A required DDEX element is absent from the manifest.", severity: "critical", layer: "ddex", dsp: null },
  // ── Fraud
  { id: "fraud.duplicate_isrc", title: "Duplicate ISRC across orgs", description: "This ISRC was already registered to a different organization.", severity: "critical", layer: "fraud", dsp: null, fixHint: "Verify ISRC ownership or obtain a new code." },
  { id: "fraud.artist_name_similarity", title: "Potential artist name impersonation", description: "The artist name closely matches a well-known artist name.", severity: "warning", layer: "fraud", dsp: null },
  { id: "fraud.release_velocity_high", title: "High release velocity flagged", description: "Unusually high number of releases in a short period detected.", severity: "warning", layer: "fraud", dsp: null },
  // ── DSP-specific
  { id: "spotify.metadata.explicit_content_tag", title: "Explicit flag required (Spotify)", description: "Tracks containing explicit lyrics must be tagged with the explicit content flag.", severity: "warning", layer: "metadata", dsp: "spotify" },
  { id: "apple.metadata.parental_advisory", title: "Parental advisory required (Apple)", description: "Apple Music requires explicit/clean designation on all tracks.", severity: "warning", layer: "metadata", dsp: "apple" },
  { id: "tiktok.metadata.short_clip_duration", title: "Track too short for TikTok", description: "TikTok requires tracks to be at least 60 seconds.", severity: "warning", layer: "metadata", dsp: "tiktok" },
  { id: "youtube.metadata.content_id_required", title: "Content ID metadata required (YouTube)", description: "Publisher and composer fields are required for YouTube Content ID registration.", severity: "warning", layer: "metadata", dsp: "youtube" },
];

const LAYERS = ["metadata", "ddex", "artwork", "audio", "fraud", "enrichment"] as const;
const LAYER_COLORS: Record<string, string> = {
  metadata: "bg-blue-100 text-blue-700",
  ddex: "bg-violet-100 text-violet-700",
  artwork: "bg-pink-100 text-pink-700",
  audio: "bg-amber-100 text-amber-700",
  fraud: "bg-red-100 text-red-700",
  enrichment: "bg-emerald-100 text-emerald-700",
};
const SEV_COLORS: Record<Severity, string> = {
  critical: "bg-red-100 text-red-700",
  warning: "bg-amber-100 text-amber-700",
  info: "bg-blue-50 text-blue-600",
};

export default function RulesPage() {
  const [layerFilter, setLayerFilter] = useState<string | null>(null);
  const [sevFilter, setSevFilter] = useState<Severity | null>(null);
  const [query, setQuery] = useState("");

  const filtered = RULES.filter((r) => {
    if (layerFilter && r.layer !== layerFilter) return false;
    if (sevFilter && r.severity !== sevFilter) return false;
    if (query) {
      const q = query.toLowerCase();
      return r.title.toLowerCase().includes(q) || r.id.toLowerCase().includes(q) || r.description.toLowerCase().includes(q);
    }
    return true;
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Rules</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Built-in QA rules applied automatically during every scan — {RULES.length} total.
        </p>
      </div>

      {/* How rules work */}
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-5">
        <h2 className="mb-2 text-sm font-semibold text-slate-800">How rules work</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 text-xs text-slate-600">
          <div className="flex gap-2">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-700 font-bold text-xs">!</span>
            <div><span className="font-semibold text-red-700">Critical</span> — blocks delivery to DSPs. Must be resolved before submission.</div>
          </div>
          <div className="flex gap-2">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-700 font-bold text-xs">!</span>
            <div><span className="font-semibold text-amber-700">Warning</span> — may cause rejection or poor placement. Recommended to fix.</div>
          </div>
          <div className="flex gap-2">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-700 font-bold text-xs">i</span>
            <div><span className="font-semibold text-blue-700">Info</span> — advisory suggestions from MusicBrainz enrichment. No score impact.</div>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search rules…"
          className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 placeholder-slate-400 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400 w-52"
        />
        <div className="flex flex-wrap gap-1.5">
          {LAYERS.map((l) => (
            <button
              key={l}
              onClick={() => setLayerFilter(layerFilter === l ? null : l)}
              className={cn(
                "rounded-full px-2.5 py-1 text-xs font-medium transition-colors capitalize",
                layerFilter === l ? LAYER_COLORS[l] + " ring-1 ring-current" : "bg-slate-100 text-slate-500 hover:bg-slate-200"
              )}
            >
              {l}
            </button>
          ))}
        </div>
        <div className="flex gap-1.5">
          {(["critical", "warning", "info"] as Severity[]).map((s) => (
            <button
              key={s}
              onClick={() => setSevFilter(sevFilter === s ? null : s)}
              className={cn(
                "rounded-full px-2.5 py-1 text-xs font-medium transition-colors capitalize",
                sevFilter === s ? SEV_COLORS[s] + " ring-1 ring-current" : "bg-slate-100 text-slate-500 hover:bg-slate-200"
              )}
            >
              {s}
            </button>
          ))}
        </div>
        {(layerFilter || sevFilter || query) && (
          <button
            onClick={() => { setLayerFilter(null); setSevFilter(null); setQuery(""); }}
            className="text-xs font-medium text-slate-400 hover:text-slate-600"
          >
            Clear
          </button>
        )}
        <span className="ml-auto text-xs text-slate-400">{filtered.length} rules</span>
      </div>

      {/* Rules list */}
      <div className="rounded-lg border border-slate-200 bg-white shadow-sm overflow-hidden">
        {filtered.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-slate-400 text-sm">No rules match your filters.</div>
        ) : (
          <div className="divide-y divide-slate-50">
            {filtered.map((rule) => (
              <div key={rule.id} className="flex items-start gap-4 px-5 py-4 hover:bg-slate-50/60">
                <span className={cn("mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold capitalize", SEV_COLORS[rule.severity])}>
                  {rule.severity}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-0.5">
                    <p className="text-sm font-medium text-slate-800">{rule.title}</p>
                    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium capitalize", LAYER_COLORS[rule.layer] ?? "bg-slate-100 text-slate-500")}>
                      {rule.layer}
                    </span>
                    {rule.dsp && (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500 capitalize">
                        {rule.dsp}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-500 leading-relaxed">{rule.description}</p>
                  {rule.fixHint && (
                    <p className="mt-1 text-xs text-indigo-600">
                      Fix: {rule.fixHint}
                    </p>
                  )}
                </div>
                <code className="shrink-0 hidden sm:block rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-400 font-mono">
                  {rule.id.split(".").slice(-1)[0].replace(/_/g, "-")}
                </code>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
