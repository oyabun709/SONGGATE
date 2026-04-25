"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@clerk/nextjs";
import Link from "next/link";
import {
  Zap,
  ShieldCheck,
  Database,
  FileCheck2,
  Hash,
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
      "Run 40+ rules across DDEX ERN 4.3 structure, DSP-specific metadata, artwork resolution, and fraud signals before delivery. Every release gets a readiness score and a plain-English fix list.",
    color: "text-indigo-600",
    bg: "bg-indigo-50",
  },
  {
    icon: Database,
    title: "Bulk catalog validation",
    description:
      "Submit your entire catalog for pre-delivery QA. SONGGATE catches duplicate EANs, artist name inconsistencies, and missing identifiers across hundreds of releases before they propagate into downstream rights systems.",
    color: "text-emerald-600",
    bg: "bg-emerald-50",
  },
  {
    icon: FileCheck2,
    title: "Reference file compliance",
    description:
      "Validate EAN and ISRC reference files against submission requirements. Catches NARM code errors, missing country codes, invalid label fields, and duplicate identifiers — before the submission cutoff.",
    color: "text-violet-600",
    bg: "bg-violet-50",
  },
  {
    icon: Hash,
    title: "Identifier validation",
    description:
      "ISNI and ISWC checks on every submission. Flags missing identifiers, format errors, and artist name inconsistencies that cause matching failures in downstream rights and royalty systems.",
    color: "text-amber-600",
    bg: "bg-amber-50",
  },
  {
    icon: GitBranch,
    title: "Built for your pipeline",
    description:
      "REST API, webhooks, and dashboard. Accepts DDEX ERN 4.3, CSV, JSON, bulk EAN registration, and ISRC reference files. Drops into your existing workflow or runs standalone.",
    color: "text-indigo-600",
    bg: "bg-indigo-50",
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
            <span className="font-semibold tracking-tight">SONGGATE</span>
          </div>
          <div className="flex items-center gap-4">
            <Link
              href="/sign-in"
              className="text-sm text-slate-600 hover:text-slate-900"
            >
              Sign in
            </Link>
            <a
              href="mailto:andrew@housesonhills.io?subject=SONGGATE Demo Request"
              className="rounded-md bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 transition-colors"
            >
              Book a demo
            </a>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-5xl px-6 pb-20 pt-24 text-center">
        <h1 className="text-4xl font-bold leading-tight tracking-tight text-slate-900 sm:text-5xl lg:text-6xl">
          Catch release errors
          <br />
          <span className="text-indigo-600">before they cost you.</span>
        </h1>
        <p className="mx-auto mt-6 max-w-xl text-lg text-slate-500">
          SONGGATE validates single releases, full catalogs, and reference files
          before they reach DSPs or downstream rights systems. One readiness
          score. Plain-English fixes. Built for labels, distributors, and rights
          operations teams.
        </p>
        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3 sm:gap-4">
          <a
            href="mailto:andrew@housesonhills.io?subject=SONGGATE Demo Request"
            className="flex items-center gap-2 rounded-lg bg-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 transition-colors"
          >
            Book a demo <ArrowRight className="h-4 w-4" />
          </a>
          <Link
            href="/demo"
            className="flex items-center gap-2 rounded-lg border border-slate-200 px-6 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            See live demo <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
        <p className="mt-4 text-sm text-slate-400">
          or email us at{" "}
          <a href="mailto:andrew@housesonhills.io" className="underline hover:text-slate-600">
            andrew@housesonhills.io
          </a>
        </p>
      </section>

      {/* Demo preview */}
      <section className="bg-slate-50 py-20">
        <div className="mx-auto max-w-4xl px-6">
          <p className="mb-8 text-center text-sm font-medium uppercase tracking-widest text-slate-400">
            What SONGGATE catches on a real release
          </p>
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            {/* Fake browser chrome */}
            <div className="flex h-9 items-center gap-1.5 border-b border-slate-100 bg-slate-50 px-4">
              <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
              <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
              <span className="ml-4 rounded border border-slate-200 bg-white px-3 py-0.5 text-[11px] text-slate-400">
                songgate.io/scans/demo
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-slate-100 p-6">
              <div className="pb-6 sm:pb-0 sm:pr-6">
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
              <div className="pt-6 sm:pt-0 sm:pl-6">
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
          One platform. Every stage
          <br />
          of delivery.
        </h2>
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-3">
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
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 sm:gap-8 text-center">
            {[
              { stat: "40+", label: "Validation rules" },
              { stat: "2", label: "Reference file formats supported" },
              { stat: "15", label: "DSP readiness profiles" },
              { stat: "Weekly", label: "Submission tracking" },
            ].map(({ stat, label }) => (
              <div key={label}>
                <div className="text-3xl font-bold text-slate-900">{stat}</div>
                <div className="mt-1 text-sm text-slate-500">{label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Schedule a call */}
      <section className="mx-auto max-w-3xl px-6 py-24 text-center">
        <h2 className="mb-4 text-3xl font-bold tracking-tight">
          See SONGGATE in action
        </h2>
        <p className="mb-8 text-lg text-slate-500">
          We&apos;ll walk you through a live demo, discuss your release workflow,
          and put together a plan that fits your team. Your first 5 scans are
          free — no commitment required.
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
          <Link
            href="/demo"
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-8 py-3 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 transition-colors"
          >
            Try the live demo <ArrowRight className="h-4 w-4" />
          </Link>
          <a
            href="mailto:andrew@housesonhills.io?subject=SONGGATE Demo Request"
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-8 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-colors"
          >
            Schedule a call <ArrowRight className="h-4 w-4" />
          </a>
        </div>
        <p className="mt-5 text-sm text-slate-400">
          Reach us directly at{" "}
          <a href="mailto:andrew@housesonhills.io" className="underline hover:text-slate-600">
            andrew@housesonhills.io
          </a>
        </p>
      </section>

      {/* CTA */}
      <section className="bg-indigo-600 py-20 text-center text-white">
        <h2 className="mb-4 text-3xl font-bold tracking-tight">
          Ready to catch errors before
          <br />
          they cost you?
        </h2>
        <p className="mb-8 text-indigo-200">
          SONGGATE works for labels, distributors, and rights operations teams.
          Email us and we&apos;ll show you how it fits your specific workflow.
        </p>
        <a
          href="mailto:andrew@housesonhills.io?subject=SONGGATE Demo Request"
          className="inline-flex items-center gap-2 rounded-lg bg-white px-8 py-3 text-sm font-semibold text-indigo-700 hover:bg-indigo-50 transition-colors"
        >
          Get in touch <ArrowRight className="h-4 w-4" />
        </a>
        <p className="mt-5 text-sm text-indigo-200">
          or email{" "}
          <a href="mailto:andrew@housesonhills.io" className="underline hover:text-white">
            andrew@housesonhills.io
          </a>
          {" "}directly
        </p>
      </section>

      {/* Footer */}
      <footer className="border-t border-slate-100 py-8">
        <div className="mx-auto max-w-5xl px-6 text-xs text-slate-400">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 sm:gap-0">
            <div className="flex items-center gap-2">
              <Zap className="h-3.5 w-3.5 text-indigo-500" />
              <span>© 2026 SONGGATE</span>
            </div>
            <div className="flex items-center gap-6">
              <Link href="/sign-in" className="hover:text-slate-600">
                Sign in
              </Link>
              <a href="mailto:andrew@housesonhills.io" className="hover:text-slate-600">
                andrew@housesonhills.io
              </a>
              <a
                href="https://api.songgate.io/docs"
                className="hover:text-slate-600"
              >
                API docs
              </a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
