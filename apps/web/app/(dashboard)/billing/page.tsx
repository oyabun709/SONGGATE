"use client";

import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@clerk/nextjs";
import { useSearchParams } from "next/navigation";
import {
  Zap,
  CheckCircle2,
  ExternalLink,
  FileText,
  AlertTriangle,
  Loader2,
  ArrowRight,
  CreditCard,
  Key,
  RefreshCw,
  XCircle,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getBillingPlans,
  getSubscription,
  createCheckoutSession,
  createPortalSession,
  getInvoices,
  type PlanInfo,
  type Subscription,
  type Invoice,
} from "@/lib/api";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(cents: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(cents);
}

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });
}

function StatusBadge({ status }: { status: string | null }) {
  if (!status)
    return (
      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
        No subscription
      </span>
    );
  const map: Record<string, string> = {
    active:   "bg-emerald-100 text-emerald-700",
    trialing: "bg-blue-100 text-blue-700",
    past_due: "bg-amber-100 text-amber-700",
    canceled: "bg-slate-100 text-slate-500",
    unpaid:   "bg-red-100 text-red-700",
  };
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold capitalize", map[status] ?? "bg-slate-100 text-slate-500")}>
      {status.replace("_", " ")}
    </span>
  );
}

// ─── Usage meter ──────────────────────────────────────────────────────────────

function UsageMeter({ sub }: { sub: Subscription }) {
  const unlimited = sub.scan_limit === -1;
  const pct = unlimited ? 0 : Math.min(100, (sub.scan_count / sub.scan_limit) * 100);
  const danger = pct >= 90;
  const warn   = pct >= 70;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-900">Usage this period</h2>
        {sub.period_end && (
          <span className="text-xs text-slate-400">Resets {fmtDate(sub.period_end)}</span>
        )}
      </div>

      <div className="flex items-end justify-between mb-2">
        <div>
          <span className="text-3xl font-bold tabular-nums text-slate-900">
            {sub.scan_count.toLocaleString()}
          </span>
          <span className="ml-1.5 text-sm text-slate-400">
            {unlimited ? "scans (unlimited)" : `/ ${sub.scan_limit.toLocaleString()} scans`}
          </span>
        </div>
        {!unlimited && (
          <span
            className={cn("text-sm font-semibold tabular-nums",
              danger ? "text-red-600" : warn ? "text-amber-600" : "text-slate-500"
            )}
          >
            {pct.toFixed(0)}%
          </span>
        )}
      </div>

      {!unlimited && (
        <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500",
              danger ? "bg-red-500" : warn ? "bg-amber-400" : "bg-indigo-500"
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}

      {danger && !unlimited && (
        <p className="mt-2 flex items-center gap-1.5 text-xs font-medium text-red-600">
          <AlertTriangle className="h-3.5 w-3.5" />
          Approaching limit — upgrade to avoid disruption
        </p>
      )}
    </div>
  );
}

// ─── Plan card ────────────────────────────────────────────────────────────────

function PlanCard({
  plan,
  current,
  onSelect,
  loading,
}: {
  plan: PlanInfo;
  current: boolean;
  onSelect: (priceId: string) => void;
  loading: boolean;
}) {
  const isCurrent = current;
  const isEnterprise = plan.id === "enterprise";

  return (
    <div
      className={cn(
        "relative flex flex-col rounded-xl border p-6 shadow-sm transition-shadow",
        isCurrent
          ? "border-indigo-300 bg-indigo-50/60 ring-1 ring-indigo-300"
          : "border-slate-200 bg-white hover:shadow-md"
      )}
    >
      {isCurrent && (
        <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-indigo-600 px-3 py-0.5 text-xs font-semibold text-white shadow">
          Current plan
        </span>
      )}

      <div className="mb-4">
        <h3 className="text-base font-bold text-slate-900">{plan.name}</h3>
        <div className="mt-1 flex items-baseline gap-1">
          {isEnterprise ? (
            <span className="text-2xl font-bold text-slate-900">Custom</span>
          ) : (
            <>
              <span className="text-3xl font-bold text-slate-900">
                {fmt(plan.price_monthly_usd)}
              </span>
              <span className="text-sm text-slate-400">/month</span>
            </>
          )}
        </div>
        <p className="mt-1 text-xs text-slate-400">
          {plan.scan_limit === -1 ? "Unlimited scans" : `${plan.scan_limit.toLocaleString()} scans/month`}
        </p>
      </div>

      <ul className="mb-6 flex-1 space-y-2">
        {plan.features.map((f) => (
          <li key={f} className="flex items-start gap-2 text-xs text-slate-600">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
            {f}
          </li>
        ))}
      </ul>

      {isEnterprise ? (
        <a
          href="mailto:sales@ropqa.io"
          className="flex items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
        >
          Contact sales <ArrowRight className="h-3.5 w-3.5" />
        </a>
      ) : isCurrent ? (
        <button
          disabled
          className="rounded-lg bg-indigo-100 py-2.5 text-sm font-semibold text-indigo-600 opacity-60"
        >
          Current plan
        </button>
      ) : (
        <button
          onClick={() => plan.price_id && onSelect(plan.price_id)}
          disabled={loading || !plan.price_id}
          className="flex items-center justify-center gap-2 rounded-lg bg-indigo-600 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-60"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {plan.price_id ? "Upgrade" : "Contact sales"}
        </button>
      )}
    </div>
  );
}

// ─── Invoice row ─────────────────────────────────────────────────────────────

function InvoiceRow({ inv }: { inv: Invoice }) {
  const statusCls: Record<string, string> = {
    paid:   "bg-emerald-100 text-emerald-700",
    open:   "bg-amber-100 text-amber-700",
    void:   "bg-slate-100 text-slate-400",
    draft:  "bg-slate-100 text-slate-400",
  };
  return (
    <tr className="hover:bg-slate-50/60">
      <td className="px-5 py-3 text-xs font-mono text-slate-500">{inv.number ?? inv.id.slice(-8)}</td>
      <td className="px-5 py-3 text-xs text-slate-500">
        {fmtDate(inv.period_start)} – {fmtDate(inv.period_end)}
      </td>
      <td className="px-5 py-3">
        <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold capitalize", statusCls[inv.status] ?? "bg-slate-100 text-slate-500")}>
          {inv.status}
        </span>
      </td>
      <td className="px-5 py-3 text-sm font-semibold tabular-nums text-slate-800">
        {fmt(inv.amount_paid_usd)} {inv.currency}
      </td>
      <td className="px-5 py-3 text-right">
        {inv.invoice_pdf && (
          <a
            href={inv.invoice_pdf}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-700"
          >
            <FileText className="h-3.5 w-3.5" /> PDF
          </a>
        )}
      </td>
    </tr>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function BillingPage() {
  const { getToken } = useAuth();
  const searchParams = useSearchParams();
  const checkoutResult = searchParams.get("checkout");

  const [token, setToken]         = useState("");
  const [sub, setSub]             = useState<Subscription | null>(null);
  const [plans, setPlans]         = useState<PlanInfo[]>([]);
  const [invoices, setInvoices]   = useState<Invoice[]>([]);
  const [loading, setLoading]     = useState(true);
  const [upgrading, setUpgrading] = useState(false);
  const [portaling, setPortaling] = useState(false);
  const [showInvoices, setShowInvoices] = useState(false);

  const fetchAll = useCallback(async (tok?: string) => {
    const t = tok ?? token;
    if (!t) return;
    setLoading(true);
    try {
      const [s, p, inv] = await Promise.all([
        getSubscription(t),
        getBillingPlans(t),
        getInvoices(t),
      ]);
      setSub(s);
      setPlans(p);
      setInvoices(inv);
    } catch {
      /* empty */
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    getToken().then((t) => { if (t) { setToken(t); fetchAll(t); } });
  }, [getToken, fetchAll]);

  async function handleUpgrade(priceId: string) {
    if (!token) return;
    setUpgrading(true);
    try {
      const { url } = await createCheckoutSession(priceId, token);
      window.location.href = url;
    } catch {
      setUpgrading(false);
    }
  }

  async function handlePortal() {
    if (!token) return;
    setPortaling(true);
    try {
      const { url } = await createPortalSession(token);
      window.location.href = url;
    } catch {
      setPortaling(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Billing</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Manage your plan, usage, and payment methods.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => fetchAll()}
            className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
          {sub?.tier !== "starter" && (
            <button
              onClick={handlePortal}
              disabled={portaling}
              className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-indigo-700 disabled:opacity-60"
            >
              {portaling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CreditCard className="h-3.5 w-3.5" />}
              Manage subscription
            </button>
          )}
        </div>
      </div>

      {/* ── Checkout result banner ──────────────────────────────────────────── */}
      {checkoutResult === "success" && (
        <div className="flex items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-5 py-4">
          <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />
          <div>
            <p className="text-sm font-semibold text-emerald-800">Subscription activated!</p>
            <p className="text-xs text-emerald-600">Your plan has been upgraded. All features are now available.</p>
          </div>
        </div>
      )}
      {checkoutResult === "canceled" && (
        <div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-5 py-4">
          <XCircle className="h-5 w-5 shrink-0 text-slate-400" />
          <p className="text-sm text-slate-600">Checkout was canceled — your plan was not changed.</p>
        </div>
      )}

      {/* ── Current plan + usage ────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Current plan */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-900">Current plan</h2>
            <StatusBadge status={sub?.status ?? null} />
          </div>
          <div className="flex items-baseline gap-2">
            <Zap className="h-5 w-5 text-indigo-500" />
            <span className="text-2xl font-bold text-slate-900">{sub?.plan_name ?? "—"}</span>
          </div>
          {sub?.period_end && (
            <p className="mt-2 text-xs text-slate-400">
              Next renewal: {fmtDate(sub.period_end)}
            </p>
          )}
          {sub?.tier === "starter" && (
            <p className="mt-3 text-xs text-slate-500">
              On the free Starter tier. Upgrade to unlock all QA layers and API access.
            </p>
          )}
        </div>

        {/* Usage meter */}
        {sub && <UsageMeter sub={sub} />}
      </div>

      {/* ── Plans ───────────────────────────────────────────────────────────── */}
      <div>
        <h2 className="mb-4 text-sm font-semibold text-slate-900">Plans</h2>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {plans.map((plan) => (
            <PlanCard
              key={plan.id}
              plan={plan}
              current={sub?.tier === plan.id}
              onSelect={handleUpgrade}
              loading={upgrading}
            />
          ))}
        </div>
      </div>

      {/* ── Invoices ────────────────────────────────────────────────────────── */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <button
          className="flex w-full items-center justify-between px-6 py-4 text-left"
          onClick={() => setShowInvoices((s) => !s)}
        >
          <h2 className="text-sm font-semibold text-slate-900">
            Invoice history
            {invoices.length > 0 && (
              <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
                {invoices.length}
              </span>
            )}
          </h2>
          {showInvoices ? <ChevronUp className="h-4 w-4 text-slate-400" /> : <ChevronDown className="h-4 w-4 text-slate-400" />}
        </button>

        {showInvoices && (
          <>
            {invoices.length === 0 ? (
              <div className="border-t border-slate-100 px-6 py-8 text-center text-sm text-slate-400">
                No invoices yet.
              </div>
            ) : (
              <div className="overflow-x-auto border-t border-slate-100">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100">
                      {["Invoice #", "Period", "Status", "Amount", ""].map((h) => (
                        <th key={h} className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-50">
                    {invoices.map((inv) => <InvoiceRow key={inv.id} inv={inv} />)}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>

      {/* ── API key notice ───────────────────────────────────────────────────── */}
      {(sub?.tier === "pro" || sub?.tier === "enterprise") && (
        <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-5">
          <div className="flex items-start gap-3">
            <Key className="mt-0.5 h-4 w-4 shrink-0 text-indigo-600" />
            <div>
              <p className="text-sm font-semibold text-indigo-900">API access included</p>
              <p className="mt-0.5 text-xs text-indigo-700">
                Your plan includes public API access. Generate and manage API keys via the API or CLI.
                See <code className="rounded bg-indigo-100 px-1 py-0.5 font-mono text-indigo-800">POST /api/v1/keys</code> in the{" "}
                <a href="/docs" target="_blank" rel="noreferrer" className="font-medium underline underline-offset-2">
                  API docs <ExternalLink className="inline h-3 w-3" />
                </a>.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
