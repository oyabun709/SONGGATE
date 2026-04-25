import Link from "next/link";
import { Zap, Terminal, Key, Scan, BarChart2, Webhook, ArrowRight, Book } from "lucide-react";

// ── Static public docs page ───────────────────────────────────────────────────
// Route: /docs (no auth required)

const BASE = "https://api.songgate.io";

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="space-y-4 scroll-mt-20">
      <h2 className="text-xl font-semibold text-slate-900 border-b border-slate-100 pb-3">{title}</h2>
      {children}
    </section>
  );
}

function CodeBlock({ children, lang = "bash" }: { children: string; lang?: string }) {
  return (
    <pre className={`language-${lang} overflow-x-auto rounded-lg bg-slate-900 px-5 py-4 text-sm text-slate-100 leading-relaxed`}>
      <code>{children}</code>
    </pre>
  );
}

function Param({ name, type, required, desc }: { name: string; type: string; required?: boolean; desc: string }) {
  return (
    <div className="flex items-start gap-3 py-2 border-b border-slate-50 last:border-0">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono text-sm font-semibold text-slate-800">{name}</span>
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500 font-mono">{type}</span>
          {required && <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs font-semibold text-red-600">required</span>}
        </div>
        <p className="mt-0.5 text-sm text-slate-500">{desc}</p>
      </div>
    </div>
  );
}

function EndpointBadge({ method, path }: { method: string; path: string }) {
  const colors: Record<string, string> = {
    GET:    "bg-emerald-100 text-emerald-700",
    POST:   "bg-blue-100 text-blue-700",
    DELETE: "bg-red-100 text-red-700",
    PATCH:  "bg-amber-100 text-amber-700",
  };
  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 font-mono text-sm">
      <span className={`rounded px-2 py-0.5 text-xs font-bold uppercase ${colors[method] ?? "bg-slate-100 text-slate-600"}`}>
        {method}
      </span>
      <span className="text-slate-700">{path}</span>
    </div>
  );
}

export default function DocsPage() {
  return (
    <div className="min-h-screen bg-white text-slate-900">
      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-slate-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
          <Link href="/" className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-indigo-600" />
            <span className="font-semibold tracking-tight">SONGGATE</span>
            <span className="ml-1 text-xs font-medium text-slate-400">/</span>
            <span className="text-sm font-medium text-slate-600">Docs</span>
          </Link>
          <div className="flex items-center gap-3">
            <Link href="/sign-in" className="text-sm text-slate-600 hover:text-slate-900">Sign in</Link>
            <Link
              href="/sign-up"
              className="rounded-md bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
            >
              Get API key
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-6 py-12 flex gap-12">
        {/* Sidebar */}
        <aside className="hidden lg:block w-52 shrink-0">
          <nav className="sticky top-24 space-y-1 text-sm">
            {[
              { href: "#overview",        icon: Book,      label: "Overview" },
              { href: "#authentication",  icon: Key,       label: "Authentication" },
              { href: "#rate-limits",     icon: BarChart2, label: "Rate limits" },
              { href: "#scans",           icon: Scan,      label: "Scans" },
              { href: "#bulk",            icon: Terminal,  label: "Bulk registration" },
              { href: "#webhooks",        icon: Webhook,   label: "Webhooks" },
              { href: "#errors",          icon: Zap,       label: "Errors" },
            ].map(({ href, icon: Icon, label }) => (
              <a
                key={href}
                href={href}
                className="flex items-center gap-2 rounded-md px-3 py-1.5 text-slate-500 hover:bg-slate-50 hover:text-slate-900 transition-colors"
              >
                <Icon className="h-3.5 w-3.5 shrink-0" />
                {label}
              </a>
            ))}
          </nav>
        </aside>

        {/* Content */}
        <main className="min-w-0 flex-1 space-y-14">
          {/* Hero */}
          <div className="space-y-4">
            <div className="inline-flex items-center gap-2 rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700">
              <Zap className="h-3.5 w-3.5" /> Public API — v1
            </div>
            <h1 className="text-4xl font-bold tracking-tight text-slate-900">SONGGATE API</h1>
            <p className="text-lg text-slate-500 max-w-2xl">
              Integrate SONGGATE release validation directly into your distribution pipeline.
              Catch DDEX errors, DSP metadata issues, and bulk registration problems before they
              reach Luminate.
            </p>
            <div className="flex items-center gap-3 pt-2">
              <Link
                href="/sign-up"
                className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700"
              >
                Get started <ArrowRight className="h-4 w-4" />
              </Link>
              <a href="#authentication" className="text-sm font-medium text-indigo-600 hover:underline">
                View authentication →
              </a>
            </div>
          </div>

          {/* Overview */}
          <Section id="overview" title="Overview">
            <p className="text-slate-600 leading-relaxed">
              All API requests are made to <code className="rounded bg-slate-100 px-1.5 py-0.5 text-sm font-mono">{BASE}</code>.
              The API follows REST conventions and returns JSON for all responses.
            </p>
            <div className="grid sm:grid-cols-3 gap-4">
              {[
                { label: "Base URL",  value: BASE },
                { label: "Format",   value: "JSON" },
                { label: "Auth",     value: "Bearer API key" },
              ].map(({ label, value }) => (
                <div key={label} className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</p>
                  <p className="mt-1 font-mono text-sm text-slate-800 break-all">{value}</p>
                </div>
              ))}
            </div>
          </Section>

          {/* Authentication */}
          <Section id="authentication" title="Authentication">
            <p className="text-slate-600 leading-relaxed">
              All requests to <code className="rounded bg-slate-100 px-1.5 py-0.5 text-sm font-mono">/api/v1/</code> require
              an API key passed as a Bearer token in the <code className="rounded bg-slate-100 px-1.5 py-0.5 text-sm font-mono">Authorization</code> header.
            </p>
            <CodeBlock>{`curl ${BASE}/api/v1/scans/scan_abc123 \\
  -H "Authorization: Bearer ropqa_sk_your_key_here"`}</CodeBlock>

            <h3 className="text-base font-semibold text-slate-800 mt-6">Create a key</h3>
            <EndpointBadge method="POST" path="/api/v1/keys" />
            <CodeBlock>{`curl -X POST ${BASE}/api/v1/keys \\
  -H "Authorization: Bearer <session_token>" \\
  -H "Content-Type: application/json" \\
  -d '{"name": "Production pipeline"}'`}</CodeBlock>
            <p className="text-xs text-slate-500">
              The plaintext key is returned once. Store it securely — it cannot be retrieved again.
            </p>
          </Section>

          {/* Rate limits */}
          <Section id="rate-limits" title="Rate limits">
            <p className="text-slate-600 leading-relaxed">
              Rate limits are enforced per API key using a 60-second sliding window.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="border-b border-slate-200">
                    <th className="py-2 pr-4 text-left font-semibold text-slate-700">Plan</th>
                    <th className="py-2 pr-4 text-left font-semibold text-slate-700">Requests / min</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["Starter",    "5"],
                    ["Pro",        "30"],
                    ["Enterprise", "200"],
                  ].map(([plan, limit]) => (
                    <tr key={plan} className="border-b border-slate-100">
                      <td className="py-2 pr-4 text-slate-700">{plan}</td>
                      <td className="py-2 pr-4 font-mono text-slate-800">{limit}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-slate-600 leading-relaxed">
              Every response includes rate limit headers:
            </p>
            <CodeBlock lang="http">{`X-RateLimit-Limit: 30
X-RateLimit-Remaining: 28
X-RateLimit-Reset: 1714000060`}</CodeBlock>
            <p className="text-slate-600 leading-relaxed">
              When the limit is exceeded you receive a <code className="rounded bg-slate-100 px-1 text-sm font-mono">429</code> response with a <code className="rounded bg-slate-100 px-1 text-sm font-mono">Retry-After</code> header.
            </p>
          </Section>

          {/* Scans */}
          <Section id="scans" title="Scans">
            <p className="text-slate-600 leading-relaxed">
              Submit a release for validation. SONGGATE runs DDEX, DSP metadata, fraud, and
              enrichment layers depending on your plan.
            </p>

            <h3 className="text-base font-semibold text-slate-800">Create a scan</h3>
            <EndpointBadge method="POST" path="/api/v1/releases/{release_id}/scan" />
            <CodeBlock>{`curl -X POST ${BASE}/api/v1/releases/rel_abc123/scan \\
  -H "Authorization: Bearer ropqa_sk_your_key" \\
  -H "Content-Type: application/json" \\
  -d '{"dsps": ["spotify", "apple_music"], "layers": ["ddex", "metadata"]}'`}</CodeBlock>

            <h3 className="text-base font-semibold text-slate-800 mt-6">Poll for results</h3>
            <EndpointBadge method="GET" path="/api/v1/scans/{scan_id}" />
            <CodeBlock>{`curl ${BASE}/api/v1/scans/scan_abc123 \\
  -H "Authorization: Bearer ropqa_sk_your_key"`}</CodeBlock>
            <p className="text-sm text-slate-500">
              Poll until <code className="rounded bg-slate-100 px-1 font-mono">status</code> is{" "}
              <code className="rounded bg-slate-100 px-1 font-mono">complete</code> or <code className="rounded bg-slate-100 px-1 font-mono">failed</code>.
              Typical completion: 5–15 seconds.
            </p>

            <h3 className="text-base font-semibold text-slate-800 mt-6">Readiness grades</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="border-b border-slate-200">
                    <th className="py-2 pr-4 text-left font-semibold text-slate-700">Grade</th>
                    <th className="py-2 pr-4 text-left font-semibold text-slate-700">Score</th>
                    <th className="py-2 text-left font-semibold text-slate-700">Meaning</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["PASS", "≥ 80", "Ready for delivery"],
                    ["WARN", "≥ 60", "Minor issues — review before shipping"],
                    ["FAIL", "< 60", "Critical issues — do not ship"],
                  ].map(([grade, score, meaning]) => (
                    <tr key={grade} className="border-b border-slate-100">
                      <td className="py-2 pr-4 font-semibold text-slate-700">{grade}</td>
                      <td className="py-2 pr-4 font-mono text-slate-800">{score}</td>
                      <td className="py-2 text-slate-600">{meaning}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          {/* Bulk registration */}
          <Section id="bulk" title="Bulk registration">
            <p className="text-slate-600 leading-relaxed">
              Validate Luminate Market Share bulk registration files (pipe-delimited EAN format)
              and ISRC reference files before submission.
            </p>

            <h3 className="text-base font-semibold text-slate-800">Scan a bulk file</h3>
            <EndpointBadge method="POST" path="/scans/bulk" />
            <CodeBlock>{`curl -X POST ${BASE}/scans/bulk \\
  -H "Authorization: Bearer <clerk_token>" \\
  -F "file=@bulk_registration.txt"`}</CodeBlock>

            <h3 className="text-base font-semibold text-slate-800 mt-6">Scan an ISRC file</h3>
            <EndpointBadge method="POST" path="/scans/isrc" />
            <CodeBlock>{`curl -X POST ${BASE}/scans/isrc \\
  -H "Authorization: Bearer <clerk_token>" \\
  -F "file=@isrc_reference.txt"`}</CodeBlock>
          </Section>

          {/* Webhooks */}
          <Section id="webhooks" title="Webhooks">
            <p className="text-slate-600 leading-relaxed">
              Register an HTTPS endpoint to receive real-time event notifications.
              Every delivery is signed with HMAC-SHA256.
            </p>

            <h3 className="text-base font-semibold text-slate-800">Register an endpoint</h3>
            <EndpointBadge method="POST" path="/settings/webhooks" />
            <CodeBlock>{`curl -X POST ${BASE}/settings/webhooks \\
  -H "Authorization: Bearer <clerk_token>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "url": "https://your-app.com/hooks/songgate",
    "events": ["scan.complete", "bulk.complete"]
  }'`}</CodeBlock>

            <h3 className="text-base font-semibold text-slate-800 mt-6">Verify signatures</h3>
            <p className="text-slate-600 text-sm leading-relaxed">
              Each delivery includes an <code className="rounded bg-slate-100 px-1 font-mono">X-SONGGATE-Signature</code> header.
              Verify it to confirm the payload came from SONGGATE:
            </p>
            <CodeBlock lang="python">{`import hashlib, hmac

def verify(secret: str, body: bytes, sig_header: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig_header)`}</CodeBlock>

            <h3 className="text-base font-semibold text-slate-800 mt-6">Event types</h3>
            <div className="space-y-2">
              {[
                ["scan.complete", "A DDEX / metadata scan finished successfully"],
                ["scan.failed",   "A scan encountered a fatal error"],
                ["bulk.complete", "A bulk registration scan finished"],
                ["test.ping",     "Test delivery (sent when you click 'Test' in settings)"],
              ].map(([event, desc]) => (
                <div key={event} className="flex items-start gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5">
                  <code className="text-sm font-mono font-semibold text-indigo-700 shrink-0">{event}</code>
                  <p className="text-sm text-slate-500">{desc}</p>
                </div>
              ))}
            </div>
          </Section>

          {/* Errors */}
          <Section id="errors" title="Errors">
            <p className="text-slate-600 leading-relaxed">
              SONGGATE uses standard HTTP status codes. Error bodies follow this shape:
            </p>
            <CodeBlock lang="json">{`{
  "detail": "Invalid or revoked API key"
}`}</CodeBlock>
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="border-b border-slate-200">
                    <th className="py-2 pr-4 text-left font-semibold text-slate-700">Status</th>
                    <th className="py-2 text-left font-semibold text-slate-700">Meaning</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["400", "Bad request — malformed body or missing field"],
                    ["401", "Unauthorized — missing or invalid API key"],
                    ["403", "Forbidden — feature not available on your plan"],
                    ["404", "Not found"],
                    ["413", "Payload too large (max 5 MB for file uploads)"],
                    ["422", "Unprocessable entity — validation error"],
                    ["429", "Rate limit exceeded — see X-RateLimit-Reset"],
                    ["500", "Internal server error"],
                  ].map(([code, meaning]) => (
                    <tr key={code} className="border-b border-slate-100">
                      <td className="py-2 pr-4 font-mono font-semibold text-slate-700">{code}</td>
                      <td className="py-2 text-slate-600">{meaning}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          {/* CTA */}
          <div className="rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 to-indigo-100/50 px-8 py-10 text-center">
            <h2 className="text-2xl font-bold text-slate-900">Ready to integrate?</h2>
            <p className="mx-auto mt-3 max-w-md text-sm text-slate-500">
              Create an account to get your API key and start validating releases in minutes.
            </p>
            <div className="mt-6 flex justify-center gap-3">
              <Link
                href="/sign-up"
                className="flex items-center gap-2 rounded-lg bg-indigo-600 px-6 py-3 text-sm font-semibold text-white hover:bg-indigo-700"
              >
                Start free trial <ArrowRight className="h-4 w-4" />
              </Link>
              <a
                href="mailto:andrew@housesonhills.io?subject=SONGGATE API"
                className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-6 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50"
              >
                Contact sales
              </a>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
