"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@clerk/nextjs";
import Link from "next/link";
import {
  Zap,
  ShieldCheck,
  BarChart3,
  GitBranch,
  ArrowRight,
  CheckCircle2,
  XCircle,
} from "lucide-react";

const FEATURES = [
  {
    icon: ShieldCheck,
    title: "Pre-flight every release",
    description:
      "Run 40+ rules across DDEX structure, metadata completeness, artwork resolution, and fraud signals — before you deliver to any DSP.",
    color: "text-indigo-600",
    bg: "bg-indigo-50",
  },
  {
    icon: BarChart3,
    title: "DSP readiness scores",
    description:
      "Know exactly where you stand on Spotify, Apple Music, Amazon, Tidal, and 10+ other platforms. Each release gets a readiness score and a PASS / WARN / FAIL grade.",
    color: "text-emerald-600",
    bg: "bg-emerald-50",
  },
  {
    icon: GitBranch,
    title: "Fits your workflow",
    description:
      "Ingest DDEX ERN 4.3 packages, CSV uploads, or JSON via the REST API. Drop it into your existing pipeline or use the dashboard.",
    color: "text-violet-600",
    bg: "bg-violet-50",
  },
];

const CAUGHT_ERRORS = [
  "Missing publisher on Track 2",
  "Artwork 2000×2000 px (below 3000×3000 minimum)",
  "Malformed ISRC on Track 3",
  "Music spam signals detected (48-second track)",
];

const PASSED = [
  "DDEX ERN 4.3 schema valid",
  "All ISRCs present and unique",
  "P-Line and C-Line on all tracks",
  "Explicit flag declared",
];

const PLANS = [
  {
    name: "Starter",
    price: "$500",
    unit: "/mo",
    scans: "50 scans / month",
    features: ["DDEX + metadata validation", "Dashboard access", "PDF reports"],
    cta: "Start free trial",
    href: "/sign-up",
    highlight: false,
  },
  {
    name: "Professional",
    price: "$2,000",
    unit: "/mo",
    scans: "500 scans / month",
    features: [
      "All layers including fraud + audio",
      "REST API access",
      "Analytics dashboard",
      "Team seats",
    ],
    cta: "Start free trial",
    href: "/sign-up",
    highlight: true,
  },
  {
    name: "Enterprise",
    price: "$8,000",
    unit: "/mo",
    scans: "Unlimited scans",
    features: [
      "Everything in Pro",
      "Batch API (100 releases/request)",
      "White-label PDF reports",
      "SLA + dedicated support",
    ],
    cta: "Talk to us",
    href: "mailto:sales@ropqa.com",
    highlight: false,
  },
];

export default function LandingPage() {
  const { isSignedIn, isLoaded } = useUser();
  const router = useRouter();

  useEffect(() => {
    if (isLoaded && isSignedIn) {
      router.replace("/dashboard");
    }
  }, [isLoaded, isSignedIn, router]);

  return (
    <div className="min-h-screen bg-white text-slate-900">
      {/* Nav */}
      <header className="sticky top-0 z-50 border-b border-slate-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-6">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-indigo-600" />
            <span className="font-semibold tracking-tight">RopQA</span>
          </div>
          <div className="flex items-center gap-4">
            <Link
              href="/sign-in"
              className="text-sm text-slate-600 hover:text-slate-900"
            >
              Sign in
            </Link>
            <Link
              href="/sign-up"
              className="rounded-md bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
            >
              Start free trial
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-5xl px-6 pb-20 pt-24 text-center">
        <div className="mb-4 inline-flex items-center gap-1.5 rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">
          <Zap className="h-3 w-3" />
          Trusted by distributors delivering 10,000+ releases/month
        </div>
        <h1 className="text-5xl font-bold leading-tight tracking-tight text-slate-900 sm:text-6xl">
          Stop releasing with
          <br />
          <span className="text-indigo-600">metadata errors.</span>
        </h1>
        <p className="mx-auto mt-6 max-w-xl text-lg text-slate-500">
          Pre-flight every release before delivery. RopQA runs 40+ validation
          rules across DDEX structure, metadata, artwork, audio, and fraud
          signals — and scores your readiness for every major DSP.
        </p>
        <div className="mt-8 flex items-center justify-center gap-4">
          <Link
            href="/sign-up"
            className="flex items-center gap-2 rounded-lg bg-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700"
          >
            Start free trial
            <ArrowRight className="h-4 w-4" />
          </Link>
          <Link
            href="/onboarding"
            className="flex items-center gap-2 rounded-lg border border-slate-200 px-6 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            See a live demo
          </Link>
        </div>
        <p className="mt-4 text-xs text-slate-400">
          No credit card required for trial · Cancel anytime
        </p>
      </section>

      {/* Demo preview */}
      <section className="bg-slate-50 py-20">
        <div className="mx-auto max-w-4xl px-6">
          <p className="mb-8 text-center text-sm font-medium uppercase tracking-widest text-slate-400">
            What RopQA catches on a real release
          </p>
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            {/* Fake browser chrome */}
            <div className="flex h-9 items-center gap-1.5 border-b border-slate-100 bg-slate-50 px-4">
              <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
              <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
              <span className="ml-4 rounded border border-slate-200 bg-white px-3 py-0.5 text-[11px] text-slate-400">
                app.ropqa.com/scans/scan_demo
              </span>
            </div>
            <div className="grid grid-cols-2 divide-x divide-slate-100 p-6">
              <div className="pr-6">
                <div className="mb-3 flex items-center gap-2">
                  <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
                    FAIL
                  </span>
                  <span className="text-sm font-medium text-slate-700">
                    Luminous Decay — Nova Crest
                  </span>
                </div>
                <p className="mb-3 text-xs text-slate-400">Issues found</p>
                <ul className="space-y-2">
                  {CAUGHT_ERRORS.map((e) => (
                    <li key={e} className="flex items-start gap-2 text-sm">
                      <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
                      <span className="text-slate-700">{e}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="pl-6">
                <div className="mb-3 flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-400">
                    Passed checks
                  </span>
                </div>
                <p className="mb-3 text-xs text-slate-400">&nbsp;</p>
                <ul className="space-y-2">
                  {PASSED.map((p) => (
                    <li key={p} className="flex items-start gap-2 text-sm">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                      <span className="text-slate-500">{p}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto max-w-5xl px-6 py-20">
        <h2 className="mb-12 text-center text-3xl font-bold tracking-tight">
          Everything between your session
          <br />
          and the store shelf
        </h2>
        <div className="grid gap-8 sm:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, description, color, bg }) => (
            <div key={title} className="rounded-xl border border-slate-100 p-6">
              <div
                className={`mb-4 inline-flex rounded-lg p-2.5 ${bg}`}
              >
                <Icon className={`h-5 w-5 ${color}`} />
              </div>
              <h3 className="mb-2 font-semibold text-slate-900">{title}</h3>
              <p className="text-sm leading-relaxed text-slate-500">
                {description}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Social proof */}
      <section className="border-y border-slate-100 bg-slate-50 py-12">
        <div className="mx-auto max-w-5xl px-6">
          <p className="mb-8 text-center text-sm font-medium uppercase tracking-widest text-slate-400">
            Built for teams that ship music at scale
          </p>
          <div className="grid grid-cols-3 gap-8 text-center">
            {[
              { stat: "40+", label: "Validation rules" },
              { stat: "15 DSPs", label: "Readiness profiles" },
              { stat: "< 45s", label: "Average scan time" },
            ].map(({ stat, label }) => (
              <div key={label}>
                <div className="text-3xl font-bold text-slate-900">{stat}</div>
                <div className="mt-1 text-sm text-slate-500">{label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section className="mx-auto max-w-5xl px-6 py-20" id="pricing">
        <h2 className="mb-3 text-center text-3xl font-bold tracking-tight">
          Simple pricing
        </h2>
        <p className="mb-12 text-center text-slate-500">
          Start with a free trial. No credit card required.
        </p>
        <div className="grid gap-6 sm:grid-cols-3">
          {PLANS.map(({ name, price, unit, scans, features, cta, href, highlight }) => (
            <div
              key={name}
              className={`relative rounded-xl border p-6 ${
                highlight
                  ? "border-indigo-300 bg-indigo-50 shadow-md"
                  : "border-slate-200 bg-white"
              }`}
            >
              {highlight && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-indigo-600 px-3 py-0.5 text-xs font-semibold text-white">
                  Most popular
                </div>
              )}
              <div className="mb-1 text-sm font-semibold text-slate-500">
                {name}
              </div>
              <div className="mb-1 flex items-baseline gap-1">
                <span className="text-3xl font-bold text-slate-900">
                  {price}
                </span>
                <span className="text-sm text-slate-500">{unit}</span>
              </div>
              <div className="mb-5 text-xs text-slate-400">{scans}</div>
              <ul className="mb-6 space-y-2">
                {features.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-sm">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                    <span className="text-slate-600">{f}</span>
                  </li>
                ))}
              </ul>
              <Link
                href={href}
                className={`block w-full rounded-lg py-2.5 text-center text-sm font-semibold transition-colors ${
                  highlight
                    ? "bg-indigo-600 text-white hover:bg-indigo-700"
                    : "border border-slate-200 text-slate-700 hover:bg-slate-50"
                }`}
              >
                {cta}
              </Link>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="bg-indigo-600 py-20 text-center text-white">
        <h2 className="mb-4 text-3xl font-bold tracking-tight">
          Ready to pre-flight your next release?
        </h2>
        <p className="mb-8 text-indigo-200">
          Set up in under 30 minutes. Your first scan is free.
        </p>
        <Link
          href="/onboarding"
          className="inline-flex items-center gap-2 rounded-lg bg-white px-8 py-3 text-sm font-semibold text-indigo-700 hover:bg-indigo-50"
        >
          Get started
          <ArrowRight className="h-4 w-4" />
        </Link>
      </section>

      {/* Footer */}
      <footer className="border-t border-slate-100 py-8">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <Zap className="h-3.5 w-3.5 text-indigo-500" />
            <span>© 2024 RopQA</span>
          </div>
          <div className="flex items-center gap-6">
            <Link href="/sign-in" className="hover:text-slate-600">
              Sign in
            </Link>
            <a href="mailto:support@ropqa.com" className="hover:text-slate-600">
              Support
            </a>
            <a
              href="https://api.ropqa.com/docs"
              className="hover:text-slate-600"
            >
              API docs
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
