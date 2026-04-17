"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  XCircle,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  Shield,
  Zap,
  BarChart3,
  Lock,
  Globe,
} from "lucide-react";

const ACCENT = "#6366f1";
const BG = "#0a0a0f";

// ─── Slide data ───────────────────────────────────────────────────────────────

const SLIDES = [
  "Cover",
  "The Problem",
  "The Gap",
  "The Product",
  "Why Now",
  "The Moat",
  "Business Model",
  "Who Buys This",
  "Acquisition Landscape",
  "The Ask",
];

// ─── Individual slides ────────────────────────────────────────────────────────

function Slide01Cover() {
  const [copied, setCopied] = useState(false);
  function copyEmail() {
    navigator.clipboard.writeText("andrew@housesonhills.io").catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }
  return (
    <div className="flex flex-col items-center justify-center h-full text-center gap-6 sm:gap-8">
      <div className="flex items-center gap-3 mb-1">
        <Zap className="h-6 w-6 sm:h-8 sm:w-8" style={{ color: ACCENT }} />
        <span className="text-3xl sm:text-5xl font-black tracking-tight">SONGGATE</span>
      </div>
      <p className="text-lg sm:text-2xl font-light text-slate-300 max-w-xl leading-snug">
        Pre-flight every release.
        <br />
        <span className="text-white font-medium">Catch errors before they cost you.</span>
      </p>
      <div className="flex flex-col sm:flex-row gap-3 mt-2 w-full sm:w-auto px-4 sm:px-0">
        <button
          onClick={copyEmail}
          className="flex items-center justify-center gap-2 rounded-lg px-7 py-3 text-sm font-semibold text-white transition-opacity"
          style={{ background: ACCENT }}
        >
          {copied ? "Email copied!" : <>Book a demo <ArrowRight className="h-4 w-4" /></>}
        </button>
        <Link
          href="/onboarding"
          className="flex items-center justify-center gap-2 rounded-lg px-7 py-3 text-sm font-semibold text-slate-300 border border-slate-700 hover:border-slate-500 transition-colors"
        >
          See live product
        </Link>
      </div>
      <p className="text-xs text-slate-500 mt-1">
        or reach us at{" "}
        <a href="mailto:andrew@housesonhills.io" className="underline hover:text-slate-300 transition-colors">
          andrew@housesonhills.io
        </a>
      </p>
    </div>
  );
}

function Slide02Problem() {
  const before = [
    "Label submits release to distributor",
    "Distributor ingests and queues for delivery",
    "DSP rejects — missing publisher on Track 2",
    "Label notified 3–5 days later",
    "Rush fix, resubmit, re-queue",
    "Release date slips. Revenue lost.",
  ];
  const after = [
    "Label runs SONGGATE pre-flight scan",
    "Missing publisher flagged immediately",
    "Artwork resolution caught (2000px, needs 3000px)",
    "ISRC collision on Track 3 detected",
    "Fix everything before submission",
    "Release ships clean. On time.",
  ];

  return (
    <div className="flex flex-col h-full justify-center gap-5 sm:gap-8">
      <div>
        <h2 className="text-2xl sm:text-4xl font-bold text-center">The Problem</h2>
        <p className="text-center text-slate-400 text-sm sm:text-lg mt-1 sm:mt-2">
          Metadata errors aren't caught until it's too late.
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-6 max-w-4xl mx-auto w-full">
        <div className="rounded-xl border border-red-900/50 bg-red-950/20 p-4 sm:p-6">
          <div className="flex items-center gap-2 mb-3 sm:mb-4">
            <XCircle className="h-4 w-4 sm:h-5 sm:w-5 text-red-500" />
            <span className="font-semibold text-red-400 text-xs uppercase tracking-widest">Without SONGGATE</span>
          </div>
          <ul className="space-y-2 sm:space-y-3">
            {before.map((item, i) => (
              <li key={i} className="flex items-start gap-3 text-xs sm:text-sm text-slate-300">
                <span className="mt-0.5 text-slate-600 font-mono text-xs w-4 shrink-0">{i + 1}.</span>
                <span className={i >= 2 && i <= 4 ? "text-red-300 font-medium" : ""}>{item}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-xl border border-emerald-900/50 bg-emerald-950/20 p-4 sm:p-6">
          <div className="flex items-center gap-2 mb-3 sm:mb-4">
            <CheckCircle2 className="h-4 w-4 sm:h-5 sm:w-5 text-emerald-500" />
            <span className="font-semibold text-emerald-400 text-xs uppercase tracking-widest">With SONGGATE</span>
          </div>
          <ul className="space-y-2 sm:space-y-3">
            {after.map((item, i) => (
              <li key={i} className="flex items-start gap-3 text-xs sm:text-sm text-slate-300">
                <span className="mt-0.5 text-slate-600 font-mono text-xs w-4 shrink-0">{i + 1}.</span>
                <span className={i >= 1 && i <= 3 ? "text-emerald-300 font-medium" : ""}>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function Slide03Gap() {
  const capabilities = [
    "Pre-submission (not a gate)",
    "Distributor-agnostic",
    "DSP readiness scoring",
    "DDEX ERN native",
    "API access",
  ];
  const tools = [
    { name: "DDEX\nValidator", vals: [false, true, false, true, false] },
    { name: "FUGA /\nCD Baby", vals: [false, false, false, false, false] },
    { name: "DistroKid", vals: [false, false, false, false, false] },
    { name: "SONGGATE", vals: [true, true, true, true, true], highlight: true },
  ];

  return (
    <div className="flex flex-col h-full justify-center gap-4 sm:gap-6">
      <div>
        <h2 className="text-2xl sm:text-4xl font-bold text-center">The Gap</h2>
        <p className="text-center text-slate-400 text-sm sm:text-base mt-1">No one owns the pre-delivery QA layer.</p>
      </div>
      <div className="max-w-3xl mx-auto w-full overflow-x-auto">
        <table className="w-full text-xs sm:text-sm" style={{ minWidth: 380 }}>
          <thead>
            <tr>
              <th className="text-left py-2 sm:py-3 px-2 sm:px-4 text-slate-500 font-normal w-36 sm:w-52">Capability</th>
              {tools.map((t) => (
                <th
                  key={t.name}
                  className={`py-2 sm:py-3 px-2 sm:px-4 text-center font-semibold whitespace-pre-line ${t.highlight ? "text-white" : "text-slate-400"}`}
                  style={t.highlight ? { color: ACCENT } : {}}
                >
                  {t.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {capabilities.map((cap, ci) => (
              <tr key={cap} className={ci % 2 === 0 ? "bg-white/[0.02]" : ""}>
                <td className="py-2 sm:py-3 px-2 sm:px-4 text-slate-300 text-xs">{cap}</td>
                {tools.map((t, ti) => (
                  <td key={ti} className="py-2 sm:py-3 px-2 sm:px-4 text-center">
                    {t.vals[ci] ? (
                      <CheckCircle2 className="h-4 w-4 mx-auto text-emerald-500" />
                    ) : (
                      <XCircle className="h-4 w-4 mx-auto text-slate-700" />
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-center text-xs text-slate-600">
        Distributor validation = submission gate tied to their pipeline. SONGGATE = standalone, runs anywhere.
      </p>
    </div>
  );
}

function Slide04Product() {
  const layers = [
    { icon: Shield, label: "DDEX ERN 4.3 Schema", desc: "Structural validity, required elements, namespace checks" },
    { icon: BarChart3, label: "Metadata Completeness", desc: "Publisher, ISRC, ISWC, P-Line, C-Line, explicit flag" },
    { icon: Globe, label: "DSP Readiness", desc: "Per-platform rules for Spotify, Apple Music, Amazon, Tidal, 11 more" },
    { icon: Zap, label: "Artwork & Audio", desc: "Resolution, format, bit depth, sample rate, silence detection" },
    { icon: AlertTriangle, label: "Fraud Signals", desc: "Track duration patterns, duplicate ISRCs, artificial stream indicators" },
  ];

  const issues = [
    "Missing publisher credit on Track 2",
    "Artwork 2000×2000 px — minimum 3000×3000 for Apple Music",
    "ISRC collision: Track 3 matches existing catalog entry",
  ];

  return (
    <div className="flex flex-col h-full justify-center gap-4 sm:gap-6">
      <h2 className="text-2xl sm:text-4xl font-bold text-center">The Product</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-6 max-w-5xl mx-auto w-full">
        <div className="space-y-2 sm:space-y-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-2 sm:mb-4">5 Validation Layers</p>
          {layers.map(({ icon: Icon, label, desc }) => (
            <div key={label} className="flex items-start gap-3 rounded-lg border border-slate-800 bg-white/[0.02] p-2.5 sm:p-3">
              <div className="mt-0.5 rounded-md p-1.5 shrink-0" style={{ background: `${ACCENT}22` }}>
                <Icon className="h-3.5 w-3.5 sm:h-4 sm:w-4" style={{ color: ACCENT }} />
              </div>
              <div>
                <div className="text-xs sm:text-sm font-medium text-white">{label}</div>
                <div className="text-xs text-slate-500 mt-0.5">{desc}</div>
              </div>
            </div>
          ))}
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-2 sm:mb-4">Live Scan Result</p>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden">
            <div className="flex items-center justify-between p-3 sm:p-4 border-b border-slate-800">
              <div>
                <div className="font-semibold text-white text-sm sm:text-base">Luminous Decay — Nova Crest</div>
                <div className="text-xs text-slate-500 mt-0.5">3 tracks · DDEX ERN 4.3 · 2026-04-14</div>
              </div>
              <div className="text-right">
                <div className="text-2xl sm:text-3xl font-black text-red-400">42</div>
                <div className="rounded-full bg-red-900/50 px-2 py-0.5 text-xs font-semibold text-red-400 text-center mt-1">
                  FAIL
                </div>
              </div>
            </div>
            <div className="p-3 sm:p-4 space-y-2">
              <p className="text-xs text-slate-500 mb-2 sm:mb-3 font-semibold uppercase tracking-widest">Issues Found</p>
              {issues.map((issue, i) => (
                <div key={i} className="flex items-start gap-2 text-xs sm:text-sm">
                  <XCircle className="h-3.5 w-3.5 sm:h-4 sm:w-4 mt-0.5 shrink-0 text-red-500" />
                  <span className="text-slate-300">{issue}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Slide05WhyNow() {
  const catalysts = [
    {
      icon: "📋",
      title: "DDEX ERN 4.3 Mandate — March 2026",
      body: "Major DSPs have begun requiring ERN 4.3 compliance for new deliveries. Legacy ERN 3.x packages face rejection. Labels scrambling to validate updated schemas.",
      tag: "Active now",
      tagColor: "text-red-400 bg-red-900/30",
    },
    {
      icon: "💸",
      title: "Spotify Per-Track Fines for Fraud",
      body: "Spotify introduced per-track royalty penalties for artificial streaming signals and spam content. One mis-flagged release can claw back months of royalties.",
      tag: "Revenue risk",
      tagColor: "text-amber-400 bg-amber-900/30",
    },
    {
      icon: "⚖️",
      title: "DOJ $8M Music Fraud Prosecution — 2024",
      body: "The DOJ prosecuted a $8M streaming fraud scheme. Distributors and labels face increased legal and reputational risk for metadata abuse. Pre-flight is now a compliance layer.",
      tag: "Legal precedent",
      tagColor: "text-violet-400 bg-violet-900/30",
    },
  ];

  return (
    <div className="flex flex-col h-full justify-center gap-4 sm:gap-6">
      <div>
        <h2 className="text-2xl sm:text-4xl font-bold text-center">Why Now</h2>
        <p className="text-center text-slate-400 text-sm sm:text-base mt-1">Three forcing functions converging in 2025–2026.</p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-5 max-w-5xl mx-auto w-full">
        {catalysts.map(({ icon, title, body, tag, tagColor }) => (
          <div key={title} className="rounded-xl border border-slate-800 bg-white/[0.02] p-4 sm:p-5 flex flex-col gap-2 sm:gap-3">
            <div className="flex sm:block items-center gap-3">
              <span className="text-2xl sm:text-3xl">{icon}</span>
              <span className={`text-xs font-semibold rounded-full px-2 py-0.5 ${tagColor}`}>{tag}</span>
            </div>
            <h3 className="font-semibold text-white text-sm leading-snug">{title}</h3>
            <p className="text-xs text-slate-400 leading-relaxed">{body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function Slide06Moat() {
  const moats = [
    {
      icon: Shield,
      title: "Release Incident Corpus",
      body: "Every scan builds a proprietary dataset of real-world metadata errors, DSP rejection patterns, and fraud signals. The model gets sharper with every release scanned. Competitors start from zero.",
    },
    {
      icon: BarChart3,
      title: "DSP Rules Library",
      body: "15+ platform-specific readiness profiles maintained as DSPs update their requirements. This is ongoing operational work that compounds — impossible to replicate without years of DSP relationships.",
    },
    {
      icon: Lock,
      title: "API-First Pipeline Embedding",
      body: "Labels and distributors integrate SONGGATE into their delivery DAM or CI pipeline. Once embedded, switching cost is high. API customers renew at 95%+ in comparable B2B SaaS.",
    },
  ];

  return (
    <div className="flex flex-col h-full justify-center gap-4 sm:gap-6">
      <div>
        <h2 className="text-2xl sm:text-4xl font-bold text-center">The Moat</h2>
        <p className="text-center text-slate-400 text-sm sm:text-base mt-1">Data, rules, and pipeline depth that compounds over time.</p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-5 max-w-5xl mx-auto w-full">
        {moats.map(({ icon: Icon, title, body }) => (
          <div key={title} className="rounded-xl border border-slate-800 bg-white/[0.02] p-4 sm:p-6 flex flex-col gap-3 sm:gap-4">
            <div className="rounded-lg p-2.5 w-fit" style={{ background: `${ACCENT}22` }}>
              <Icon className="h-5 w-5 sm:h-6 sm:w-6" style={{ color: ACCENT }} />
            </div>
            <h3 className="font-semibold text-white text-sm sm:text-base">{title}</h3>
            <p className="text-xs sm:text-sm text-slate-400 leading-relaxed">{body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function Slide07BusinessModel() {
  const tiers = [
    {
      name: "Starter",
      target: "Indie labels & small distributors",
      scans: "Up to 50 scans / month",
      features: ["DDEX + metadata validation", "Dashboard access", "PDF reports"],
      highlight: false,
    },
    {
      name: "Professional",
      target: "Mid-size distributors & rights admins",
      scans: "Up to 500 scans / month",
      features: ["All 5 validation layers", "REST API access", "Analytics dashboard", "Team seats"],
      highlight: true,
    },
    {
      name: "Enterprise",
      target: "Large distributors & catalog managers",
      scans: "Unlimited scans",
      features: ["Batch API (100 releases/req)", "White-label PDF reports", "SLA + dedicated support"],
      highlight: false,
    },
  ];

  return (
    <div className="flex flex-col h-full justify-center gap-4 sm:gap-6">
      <h2 className="text-2xl sm:text-4xl font-bold text-center">Business Model</h2>
      <p className="text-center text-slate-400 text-sm sm:text-base -mt-2">Tiered SaaS subscription — priced by scan volume and team size</p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-5 max-w-4xl mx-auto w-full">
        {tiers.map(({ name, target, scans, features, highlight }) => (
          <div
            key={name}
            className="rounded-xl border p-4 sm:p-5 flex flex-col gap-2 sm:gap-3"
            style={{
              borderColor: highlight ? ACCENT : "rgb(30,32,44)",
              background: highlight ? `${ACCENT}11` : "rgba(255,255,255,0.02)",
            }}
          >
            {highlight && (
              <div className="text-xs font-semibold rounded-full px-2 py-0.5 text-center w-fit mx-auto" style={{ background: ACCENT, color: "white" }}>
                Most popular
              </div>
            )}
            <div className="text-sm font-semibold text-white">{name}</div>
            <div className="text-xs text-slate-400 leading-snug">{target}</div>
            <div className="text-xs text-slate-500">{scans}</div>
            <ul className="space-y-1.5 mt-1">
              {features.map((f) => (
                <li key={f} className="flex items-start gap-2 text-xs text-slate-400">
                  <CheckCircle2 className="h-3.5 w-3.5 mt-0.5 shrink-0 text-emerald-500" />
                  {f}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="max-w-4xl mx-auto w-full rounded-lg border border-slate-800 bg-white/[0.02] px-4 sm:px-6 py-3 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-1 sm:gap-0">
        <span className="text-xs sm:text-sm text-slate-400">Revenue model</span>
        <span className="text-xs sm:text-sm text-white font-medium">
          Annual contracts · Usage-based overages · Professional services
        </span>
      </div>
    </div>
  );
}

function Slide08WhoButsThis() {
  const buyers = [
    {
      emoji: "🏢",
      type: "Music Distributors",
      example: "Believe, FUGA, Stem, Amuse",
      why: "Reduce DSP rejections in their pipeline. Offer pre-flight as a value-add to label clients. SONGGATE becomes their QA layer.",
      urgency: "High",
    },
    {
      emoji: "🎵",
      type: "Indie Labels",
      example: "50–500 releases/year",
      why: "Too small to build internal QA but too large to absorb rejection delays. SONGGATE pays for itself on one avoided re-delivery.",
      urgency: "High",
    },
    {
      emoji: "📚",
      type: "Rights Administrators",
      example: "Publishing admins, catalog managers",
      why: "DDEX-heavy workflows, ISRC and ISWC validation, publishing metadata at scale. Existing tools don't score DSP readiness.",
      urgency: "Medium",
    },
    {
      emoji: "🎯",
      type: "Strategic Acquirers",
      example: "UMG, WMG, Believe, AudioSalad",
      why: "Buy the data corpus, rules library, and customer relationships. Faster than building. Bolt onto existing distribution stack.",
      urgency: "Long-term",
    },
  ];

  return (
    <div className="flex flex-col h-full justify-center gap-4 sm:gap-6">
      <h2 className="text-2xl sm:text-4xl font-bold text-center">Who Buys This</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4 max-w-4xl mx-auto w-full">
        {buyers.map(({ emoji, type, example, why, urgency }) => (
          <div key={type} className="rounded-xl border border-slate-800 bg-white/[0.02] p-4 sm:p-5 flex flex-col gap-2">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xl sm:text-2xl">{emoji}</span>
                <span className="font-semibold text-white text-sm sm:text-base">{type}</span>
              </div>
              <span className={`text-xs font-semibold rounded-full px-2 py-0.5 shrink-0 ${
                urgency === "High" ? "bg-emerald-900/40 text-emerald-400" :
                urgency === "Medium" ? "bg-amber-900/40 text-amber-400" :
                "bg-violet-900/40 text-violet-400"
              }`}>{urgency}</span>
            </div>
            <div className="text-xs text-slate-500">{example}</div>
            <p className="text-xs sm:text-sm text-slate-300 leading-relaxed">{why}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function Slide09Acquisition() {
  const deals = [
    {
      acquirer: "Universal Music Group",
      target: "Downtown Music (FUGA + CD Baby)",
      value: "$775M",
      year: "2023",
      why: "Distribution scale + catalog data. FUGA's B2B distribution tech was the crown jewel.",
      relevance: "Precedent for music-tech infrastructure acquisitions at scale",
    },
    {
      acquirer: "Warner Music Group",
      target: "Revelator",
      value: "Undisclosed",
      year: "2022",
      why: "Music analytics and royalty data platform. Data moat acquisition.",
      relevance: "Validates buying data/analytics layers vs. building them",
    },
    {
      acquirer: "Luminate (Billboard)",
      target: "Quansic",
      value: "Undisclosed",
      year: "2023",
      why: "Music entity resolution and metadata infrastructure.",
      relevance: "Metadata tooling is acquisition-worthy on its own",
    },
    {
      acquirer: "Strategic buyer",
      target: "SONGGATE",
      value: "$2M – $7M",
      year: "Target",
      why: "DSP rules corpus + incident dataset + API pipeline embedding. Bolt-on for any distributor or rights platform.",
      relevance: "2–3x ARR at scale, or strategic premium for data + defensibility",
      highlight: true,
    },
  ];

  return (
    <div className="flex flex-col h-full justify-center gap-4 sm:gap-6">
      <div>
        <h2 className="text-2xl sm:text-4xl font-bold text-center">Acquisition Landscape</h2>
        <p className="text-center text-slate-400 text-sm sm:text-base mt-1">Music infrastructure M&A is active. Data moats get acquired.</p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4 max-w-4xl mx-auto w-full">
        {deals.map(({ acquirer, target, value, year, why, relevance, highlight }) => (
          <div
            key={target}
            className="rounded-xl border p-4 sm:p-5 flex flex-col gap-2"
            style={{
              borderColor: highlight ? ACCENT : "rgb(30,32,44)",
              background: highlight ? `${ACCENT}11` : "rgba(255,255,255,0.02)",
            }}
          >
            {highlight && (
              <div className="text-xs font-semibold rounded-full px-2 py-0.5 w-fit" style={{ background: ACCENT, color: "white" }}>
                SONGGATE target
              </div>
            )}
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="text-xs text-slate-500">{acquirer} acquired</div>
                <div className="font-semibold text-white text-sm mt-0.5">{target}</div>
              </div>
              <div className="text-right shrink-0">
                <div className="font-black text-base sm:text-lg" style={{ color: highlight ? ACCENT : "white" }}>{value}</div>
                <div className="text-xs text-slate-500">{year}</div>
              </div>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">{why}</p>
            <div className="rounded bg-white/[0.04] px-2 py-1.5 text-xs text-slate-500">{relevance}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Slide10Ask() {
  const [copied, setCopied] = useState(false);
  function copyEmail() {
    navigator.clipboard.writeText("andrew@housesonhills.io").catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }
  const rows = [
    {
      type: "Pilot",
      icon: "🧪",
      what: "3-month free trial",
      get: "Real scan data on your catalog, full feature access, DSP readiness reports",
      ideal: "Labels with 10+ releases/quarter",
    },
    {
      type: "Partner",
      icon: "🤝",
      what: "Distribution integration",
      get: "SONGGATE as your pre-flight layer — white-label or co-branded, API or dashboard",
      ideal: "Distributors with B2B label clients",
    },
    {
      type: "Strategic",
      icon: "🎯",
      what: "Acquisition conversation",
      get: "Full data room: corpus, DSP rules library, technical architecture, growth model",
      ideal: "Infrastructure acquirers, rights platforms",
    },
  ];

  return (
    <div className="flex flex-col h-full justify-center gap-4 sm:gap-6">
      <div>
        <h2 className="text-2xl sm:text-4xl font-bold text-center">The Ask</h2>
        <p className="text-center text-slate-400 text-sm sm:text-base mt-1">Three ways to work together.</p>
      </div>
      <div className="max-w-3xl mx-auto w-full space-y-3">
        {rows.map(({ type, icon, what, get, ideal }) => (
          <div key={type} className="rounded-xl border border-slate-800 bg-white/[0.02] p-4">
            <div className="flex items-center gap-3 mb-2">
              <span className="text-xl">{icon}</span>
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest">{type}</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-1 sm:gap-4">
              <div>
                <div className="text-sm font-semibold text-white mb-1">{what}</div>
                <div className="text-xs text-slate-400 leading-relaxed">{get}</div>
              </div>
              <div className="sm:text-right mt-1 sm:mt-0">
                <div className="text-xs text-slate-500 mb-0.5">Ideal for</div>
                <div className="text-xs text-slate-300">{ideal}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="flex justify-center mt-1 sm:mt-2">
        <button
          onClick={copyEmail}
          className="flex items-center gap-2 rounded-lg px-6 sm:px-8 py-3 sm:py-3.5 text-sm font-semibold text-white shadow-lg transition-opacity"
          style={{ background: ACCENT }}
        >
          {copied ? "Email copied!" : <>Get in touch <ArrowRight className="h-4 w-4" /></>}
        </button>
      </div>
      <p className="text-center text-xs text-slate-600">
        <a href="mailto:andrew@housesonhills.io" className="underline hover:text-slate-400 transition-colors">
          andrew@housesonhills.io
        </a>
        {" "}· songgate.io
      </p>
    </div>
  );
}

const SLIDE_COMPONENTS = [
  Slide01Cover,
  Slide02Problem,
  Slide03Gap,
  Slide04Product,
  Slide05WhyNow,
  Slide06Moat,
  Slide07BusinessModel,
  Slide08WhoButsThis,
  Slide09Acquisition,
  Slide10Ask,
];

// ─── Main deck component ──────────────────────────────────────────────────────

export default function PitchDeck() {
  const [current, setCurrent] = useState(0);
  const total = SLIDES.length;
  const touchStartX = useRef<number | null>(null);

  const prev = useCallback(() => setCurrent((c) => Math.max(0, c - 1)), []);
  const next = useCallback(() => setCurrent((c) => Math.min(total - 1, c + 1)), [total]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === "ArrowDown") next();
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") prev();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [next, prev]);

  const onTouchStart = (e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
  };
  const onTouchEnd = (e: React.TouchEvent) => {
    if (touchStartX.current === null) return;
    const dx = e.changedTouches[0].clientX - touchStartX.current;
    if (Math.abs(dx) > 50) {
      if (dx < 0) next();
      else prev();
    }
    touchStartX.current = null;
  };

  const SlideComponent = SLIDE_COMPONENTS[current];

  return (
    <div
      className="min-h-screen flex flex-col select-none"
      style={{ background: BG, color: "white", fontFamily: "Inter, sans-serif" }}
      onTouchStart={onTouchStart}
      onTouchEnd={onTouchEnd}
    >
      {/* Progress bar */}
      <div className="fixed top-0 left-0 right-0 h-0.5 z-50" style={{ background: "rgba(255,255,255,0.06)" }}>
        <div
          className="h-full transition-all duration-500"
          style={{ width: `${((current + 1) / total) * 100}%`, background: ACCENT }}
        />
      </div>

      {/* Slide label */}
      <div className="fixed top-3 sm:top-4 left-0 right-0 flex justify-center z-40">
        <span className="text-[10px] sm:text-xs font-medium text-slate-600 uppercase tracking-widest">
          {current + 1} / {total} — {SLIDES[current]}
        </span>
      </div>

      {/* Main content — padded to avoid arrows on desktop, bottom nav on mobile */}
      <div className="flex-1 flex items-center justify-center px-4 sm:px-14 py-14 sm:py-20 pb-16 sm:pb-20">
        <div className="w-full max-w-5xl">
          <SlideComponent />
        </div>
      </div>

      {/* Nav arrows — desktop only (sides), mobile bottom corners */}
      <button
        onClick={prev}
        disabled={current === 0}
        className="fixed left-2 sm:left-4 bottom-4 sm:top-1/2 sm:bottom-auto sm:-translate-y-1/2 rounded-full p-2 sm:p-2.5 border border-slate-800 bg-white/[0.04] hover:bg-white/[0.08] disabled:opacity-20 disabled:cursor-not-allowed transition-all z-40"
        aria-label="Previous slide"
      >
        <ChevronLeft className="h-4 w-4 sm:h-5 sm:w-5 text-slate-400" />
      </button>
      <button
        onClick={next}
        disabled={current === total - 1}
        className="fixed right-2 sm:right-4 bottom-4 sm:top-1/2 sm:bottom-auto sm:-translate-y-1/2 rounded-full p-2 sm:p-2.5 border border-slate-800 bg-white/[0.04] hover:bg-white/[0.08] disabled:opacity-20 disabled:cursor-not-allowed transition-all z-40"
        aria-label="Next slide"
      >
        <ChevronRight className="h-4 w-4 sm:h-5 sm:w-5 text-slate-400" />
      </button>

      {/* Dot navigation */}
      <div className="fixed bottom-4 left-0 right-0 flex justify-center gap-1.5 sm:gap-2 z-40 px-12">
        {SLIDES.map((label, i) => (
          <button
            key={i}
            onClick={() => setCurrent(i)}
            title={label}
            className="rounded-full transition-all duration-300 shrink-0"
            style={{
              width: i === current ? 20 : 5,
              height: 5,
              background: i === current ? ACCENT : "rgba(255,255,255,0.2)",
            }}
            aria-label={`Go to slide ${i + 1}: ${label}`}
          />
        ))}
      </div>
    </div>
  );
}
