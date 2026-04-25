"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import {
  Zap,
  Building2,
  Music2,
  Radio,
  ChevronRight,
  CheckCircle2,
  XCircle,
  Loader2,
  Copy,
  Check,
  ArrowRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Step data ────────────────────────────────────────────────────────────────

const ORG_TYPES = [
  { id: "distributor", label: "Distributor", icon: Radio, description: "You deliver releases to DSPs on behalf of labels or artists" },
  { id: "label", label: "Record label", icon: Music2, description: "You manage your own or signed artists' catalogs" },
  { id: "rights_admin", label: "Rights administrator", icon: Building2, description: "You manage rights and publishing for existing catalogs" },
];

const TEAM_SIZES = ["Solo / 1 person", "2–10", "11–50", "51–200", "200+"];

const DSP_OPTIONS = [
  { id: "spotify", label: "Spotify" },
  { id: "apple_music", label: "Apple Music" },
  { id: "amazon", label: "Amazon Music" },
  { id: "tidal", label: "Tidal" },
  { id: "deezer", label: "Deezer" },
  { id: "youtube_music", label: "YouTube Music" },
  { id: "pandora", label: "Pandora" },
  { id: "tiktok", label: "TikTok" },
];

// ─── Demo scan results ────────────────────────────────────────────────────────

const DEMO_ISSUES = [
  {
    severity: "critical",
    rule_id: "DDEX_PUBLISHER_REQUIRED",
    layer: "metadata",
    message: "Track 2 'Neon Overflow' is missing a MusicPublisher contributor. Apple Music and Amazon require this field.",
    fix_hint: "Add a Contributor with Role=MusicPublisher to the SoundRecording element.",
  },
  {
    severity: "warning",
    rule_id: "ART_MIN_RESOLUTION",
    layer: "artwork",
    message: "Cover art is 2000×2000 px. Minimum required by Spotify, Apple Music, and Amazon is 3000×3000 px.",
    fix_hint: "Re-export artwork at 3000×3000 px or larger (RGB, JPG/PNG, ≤100 MB).",
  },
  {
    severity: "critical",
    rule_id: "DDEX_ISRC_FORMAT",
    layer: "ddex",
    message: "Track 3 has a malformed ISRC: 'USRC11607841X'. Expected format: CC-XXX-YY-NNNNN.",
    fix_hint: "Correct to US-RC1-16-07841 or obtain a valid ISRC from your registrant.",
  },
  {
    severity: "critical",
    rule_id: "FRAUD_MUSIC_SPAM",
    layer: "fraud",
    message: "Track 3 'Relaxing Study Music Background Chill' (48s) matches music spam patterns. Short tracks with generic keyword-stuffed titles are flagged by Spotify's fraud detection.",
    fix_hint: "Review this track. If legitimate, rename it and ensure duration exceeds 60 seconds.",
  },
];

const SEV_COLOR: Record<string, string> = {
  critical: "text-red-700 bg-red-50 border-red-200",
  warning: "text-amber-700 bg-amber-50 border-amber-200",
  info: "text-blue-700 bg-blue-50 border-blue-200",
};

const LAYER_LABEL: Record<string, string> = {
  ddex: "DDEX",
  metadata: "Metadata",
  artwork: "Artwork",
  audio: "Audio",
  fraud: "Fraud",
  enrichment: "Enrichment",
};

// ─── Step components ──────────────────────────────────────────────────────────

function StepOrg({
  orgType,
  setOrgType,
  teamSize,
  setTeamSize,
}: {
  orgType: string;
  setOrgType: (v: string) => void;
  teamSize: string;
  setTeamSize: (v: string) => void;
}) {
  return (
    <div className="space-y-8">
      <div>
        <h2 className="mb-1 text-2xl font-bold text-slate-900">
          Tell us about your team
        </h2>
        <p className="text-slate-500">
          This helps us configure the right validation rules for your workflow.
        </p>
      </div>

      <div>
        <p className="mb-3 text-sm font-medium text-slate-700">
          What best describes your organization?
        </p>
        <div className="grid gap-3">
          {ORG_TYPES.map(({ id, label, icon: Icon, description }) => (
            <button
              key={id}
              onClick={() => setOrgType(id)}
              className={cn(
                "flex items-start gap-4 rounded-lg border p-4 text-left transition-colors",
                orgType === id
                  ? "border-indigo-400 bg-indigo-50"
                  : "border-slate-200 hover:border-slate-300 hover:bg-slate-50"
              )}
            >
              <div
                className={cn(
                  "mt-0.5 rounded-md p-2",
                  orgType === id ? "bg-indigo-100" : "bg-slate-100"
                )}
              >
                <Icon
                  className={cn(
                    "h-4 w-4",
                    orgType === id ? "text-indigo-600" : "text-slate-500"
                  )}
                />
              </div>
              <div>
                <div className="font-medium text-slate-900">{label}</div>
                <div className="text-sm text-slate-500">{description}</div>
              </div>
              {orgType === id && (
                <CheckCircle2 className="ml-auto mt-0.5 h-4 w-4 shrink-0 text-indigo-600" />
              )}
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-3 text-sm font-medium text-slate-700">Team size</p>
        <div className="flex flex-wrap gap-2">
          {TEAM_SIZES.map((s) => (
            <button
              key={s}
              onClick={() => setTeamSize(s)}
              className={cn(
                "rounded-full border px-4 py-1.5 text-sm transition-colors",
                teamSize === s
                  ? "border-indigo-400 bg-indigo-50 text-indigo-700 font-medium"
                  : "border-slate-200 text-slate-600 hover:border-slate-300"
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function StepDemo() {
  const [scanning, setScanning] = useState(false);
  const [done, setDone] = useState(false);
  const [progress, setProgress] = useState(0);

  function startScan() {
    setScanning(true);
    setProgress(0);
    const interval = setInterval(() => {
      setProgress((p) => {
        if (p >= 100) {
          clearInterval(interval);
          setScanning(false);
          setDone(true);
          return 100;
        }
        return p + 4;
      });
    }, 80);
  }

  if (!scanning && !done) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="mb-1 text-2xl font-bold text-slate-900">
            See SONGGATE in action
          </h2>
          <p className="text-slate-500">
            We've loaded a sample DDEX ERN 4.3 package that contains 4
            intentional errors — the kind that get releases rejected or stuck in
            DSP review queues.
          </p>
        </div>

        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-start gap-3">
            <div className="rounded-md bg-white border border-slate-200 p-2">
              <Music2 className="h-5 w-5 text-slate-400" />
            </div>
            <div>
              <div className="font-medium text-slate-800">Luminous Decay</div>
              <div className="text-sm text-slate-500">Nova Crest · 3 tracks · ERN 4.3</div>
              <div className="mt-1 font-mono text-xs text-slate-400">
                docs/ddex/demo-release-with-errors.xml
              </div>
            </div>
          </div>
        </div>

        <button
          onClick={startScan}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 py-3 text-sm font-semibold text-white hover:bg-indigo-700"
        >
          <Zap className="h-4 w-4" />
          Run scan
        </button>
      </div>
    );
  }

  if (scanning) {
    const layers = ["DDEX schema", "Metadata", "Artwork", "Fraud signals"];
    const currentLayer = layers[Math.floor((progress / 100) * layers.length)];
    return (
      <div className="space-y-6">
        <div>
          <h2 className="mb-1 text-2xl font-bold text-slate-900">
            Scanning…
          </h2>
          <p className="text-slate-500">Running validation layers</p>
        </div>
        <div className="rounded-lg border border-slate-200 p-6 text-center">
          <Loader2 className="mx-auto mb-4 h-8 w-8 animate-spin text-indigo-500" />
          <div className="mb-3 text-sm font-medium text-slate-700">
            {currentLayer ?? "Finalizing…"}
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-indigo-500 transition-all duration-75"
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="mt-2 text-xs text-slate-400">{progress}%</div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="mb-1 text-2xl font-bold text-slate-900">
          Scan complete
        </h2>
        <div className="flex items-center gap-3">
          <span className="rounded-full bg-red-100 px-2.5 py-0.5 text-sm font-semibold text-red-700">
            FAIL
          </span>
          <span className="text-slate-500">
            4 issues found · Readiness score: 34
          </span>
        </div>
      </div>

      <div className="space-y-3">
        {DEMO_ISSUES.map((issue) => (
          <div
            key={issue.rule_id}
            className={cn(
              "rounded-lg border p-4",
              SEV_COLOR[issue.severity]
            )}
          >
            <div className="mb-1 flex items-center gap-2">
              <XCircle className="h-4 w-4 shrink-0" />
              <span className="text-xs font-semibold uppercase tracking-wide">
                {issue.severity}
              </span>
              <span className="ml-auto rounded bg-white/60 px-1.5 py-0.5 text-[10px] font-mono font-medium">
                {LAYER_LABEL[issue.layer]}
              </span>
            </div>
            <p className="mb-1.5 text-sm">{issue.message}</p>
            <p className="text-xs opacity-80">
              <span className="font-medium">Fix: </span>
              {issue.fix_hint}
            </p>
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700">
        <div className="flex items-center gap-2 font-medium">
          <CheckCircle2 className="h-4 w-4" />
          This is exactly what SONGGATE catches on your real releases — before
          they hit DSP ingest queues.
        </div>
      </div>
    </div>
  );
}

function StepDSPs({
  selected,
  toggle,
}: {
  selected: string[];
  toggle: (id: string) => void;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="mb-1 text-2xl font-bold text-slate-900">
          Which DSPs do you deliver to?
        </h2>
        <p className="text-slate-500">
          SONGGATE tailors validation rules and readiness scores to your target
          stores. You can change this any time.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {DSP_OPTIONS.map(({ id, label }) => {
          const active = selected.includes(id);
          return (
            <button
              key={id}
              onClick={() => toggle(id)}
              className={cn(
                "flex items-center justify-between rounded-lg border px-4 py-3 text-sm font-medium transition-colors",
                active
                  ? "border-indigo-400 bg-indigo-50 text-indigo-700"
                  : "border-slate-200 text-slate-700 hover:border-slate-300 hover:bg-slate-50"
              )}
            >
              {label}
              {active && <CheckCircle2 className="h-4 w-4 text-indigo-600" />}
            </button>
          );
        })}
      </div>

      {selected.length === 0 && (
        <p className="text-sm text-amber-600">
          Select at least one DSP to continue.
        </p>
      )}
    </div>
  );
}

function StepAccess({ apiKey }: { apiKey: string | null; loading: boolean }) {
  const [copied, setCopied] = useState(false);

  function copy() {
    if (!apiKey) return;
    navigator.clipboard.writeText(apiKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="mb-1 text-2xl font-bold text-slate-900">
          You're all set
        </h2>
        <p className="text-slate-500">
          Your API key is ready. Use it to integrate SONGGATE into your pipeline
          or start scanning from the dashboard.
        </p>
      </div>

      {apiKey ? (
        <div>
          <p className="mb-2 text-sm font-medium text-slate-700">
            Your API key — save this now, it won't be shown again
          </p>
          <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-sm">
            <span className="flex-1 select-all break-all text-slate-800">
              {apiKey}
            </span>
            <button
              onClick={copy}
              className="shrink-0 rounded-md p-1.5 text-slate-400 hover:bg-slate-200 hover:text-slate-600"
              title="Copy"
            >
              {copied ? (
                <Check className="h-4 w-4 text-emerald-500" />
              ) : (
                <Copy className="h-4 w-4" />
              )}
            </button>
          </div>
          <p className="mt-2 text-xs text-slate-400">
            Store this in your secrets manager. Use{" "}
            <code className="rounded bg-slate-100 px-1 py-0.5 text-slate-700">
              Authorization: Bearer {"{key}"}
            </code>{" "}
            on all API requests.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
          API key creation is available on Professional and Enterprise plans.
          You can generate one from{" "}
          <span className="font-medium text-slate-700">
            Settings → API Keys
          </span>{" "}
          after upgrading.
        </div>
      )}

      <div className="rounded-lg border border-indigo-100 bg-indigo-50 p-4 text-sm">
        <p className="mb-2 font-medium text-indigo-800">Quick start resources</p>
        <ul className="space-y-1 text-indigo-700">
          <li>
            <a
              href="https://api.songgate.io/docs"
              className="hover:underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              → API reference & Swagger UI
            </a>
          </li>
          <li>
            <a
              href="/docs/api/README.md"
              className="hover:underline"
            >
              → Node.js / Python code examples
            </a>
          </li>
          <li>
            <a
              href="/docs/ddex/template.xml"
              className="hover:underline"
            >
              → DDEX ERN 4.3 template
            </a>
          </li>
        </ul>
      </div>
    </div>
  );
}

// ─── Stepper shell ────────────────────────────────────────────────────────────

const STEPS = [
  { label: "Your team" },
  { label: "Live demo" },
  { label: "DSPs" },
  { label: "API access" },
];

export default function OnboardingPage() {
  const router = useRouter();
  const { getToken } = useAuth();

  const [step, setStep] = useState(0);
  const [orgType, setOrgType] = useState("");
  const [teamSize, setTeamSize] = useState("");
  const [dsps, setDsps] = useState<string[]>(["spotify", "apple_music"]);
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [keyLoading, setKeyLoading] = useState(false);

  function toggleDsp(id: string) {
    setDsps((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]
    );
  }

  function canAdvance() {
    if (step === 0) return orgType !== "" && teamSize !== "";
    if (step === 2) return dsps.length > 0;
    return true;
  }

  async function advance() {
    if (step === 2) {
      // Moving to step 3 — generate API key
      setStep(3);
      setKeyLoading(true);
      try {
        const token = await getToken();
        if (!token) return;
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/billing/api-keys`,
          {
            method: "POST",
            headers: {
              Authorization: `Bearer ${token}`,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ name: "Onboarding key" }),
          }
        );
        if (res.ok) {
          const data = await res.json();
          setApiKey(data.key);
        }
      } catch {
        // Non-fatal; show upgrade prompt
      } finally {
        setKeyLoading(false);
      }
      return;
    }

    if (step < STEPS.length - 1) {
      setStep(step + 1);
    } else {
      router.push("/dashboard");
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-white">
      {/* Top bar */}
      <div className="flex h-14 items-center border-b border-slate-100 px-6">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-indigo-600" />
          <span className="font-semibold tracking-tight text-slate-900">
            SONGGATE
          </span>
        </div>
      </div>

      <div className="mx-auto w-full max-w-lg flex-1 px-6 py-12">
        {/* Welcome header */}
        <div className="mb-10 text-center">
          <h1 className="text-2xl font-bold text-slate-900">Welcome to SONGGATE</h1>
          <p className="mt-2 text-sm text-slate-500">
            Pre-delivery release intelligence for music operations. Select your role to get started.
          </p>
        </div>

        {/* Stepper */}
        <div className="mb-10 flex items-center gap-0">
          {STEPS.map((s, i) => (
            <div key={s.label} className="flex flex-1 items-center">
              <div className="flex flex-col items-center">
                <div
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold transition-colors",
                    i < step
                      ? "bg-indigo-600 text-white"
                      : i === step
                      ? "border-2 border-indigo-600 bg-white text-indigo-600"
                      : "border border-slate-200 bg-white text-slate-400"
                  )}
                >
                  {i < step ? <Check className="h-4 w-4" /> : i + 1}
                </div>
                <span
                  className={cn(
                    "mt-1.5 text-[11px] font-medium",
                    i === step ? "text-indigo-600" : "text-slate-400"
                  )}
                >
                  {s.label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <div
                  className={cn(
                    "mb-5 h-px flex-1 transition-colors",
                    i < step ? "bg-indigo-400" : "bg-slate-200"
                  )}
                />
              )}
            </div>
          ))}
        </div>

        {/* Step content */}
        <div className="min-h-[400px]">
          {step === 0 && (
            <StepOrg
              orgType={orgType}
              setOrgType={setOrgType}
              teamSize={teamSize}
              setTeamSize={setTeamSize}
            />
          )}
          {step === 1 && <StepDemo />}
          {step === 2 && <StepDSPs selected={dsps} toggle={toggleDsp} />}
          {step === 3 && <StepAccess apiKey={apiKey} loading={keyLoading} />}
        </div>

        {/* Navigation */}
        <div className="mt-8 flex items-center justify-between">
          {step > 0 ? (
            <button
              onClick={() => setStep(step - 1)}
              className="text-sm text-slate-500 hover:text-slate-700"
            >
              ← Back
            </button>
          ) : (
            <div />
          )}
          <button
            onClick={advance}
            disabled={!canAdvance()}
            className={cn(
              "flex items-center gap-2 rounded-lg px-6 py-2.5 text-sm font-semibold transition-colors",
              canAdvance()
                ? "bg-indigo-600 text-white hover:bg-indigo-700"
                : "bg-slate-100 text-slate-400 cursor-not-allowed"
            )}
          >
            {step === STEPS.length - 1 ? (
              <>
                Go to dashboard
                <ArrowRight className="h-4 w-4" />
              </>
            ) : (
              <>
                Continue
                <ChevronRight className="h-4 w-4" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
