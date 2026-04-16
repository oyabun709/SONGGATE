"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import {
  Building2,
  ChevronRight,
  RefreshCw,
  Gift,
  AlertTriangle,
  ShieldCheck,
  Unlock,
  Ban,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  adminListOrgs,
  adminSetTrial,
  adminRevokeTrial,
  adminSetTier,
  type AdminOrg,
} from "@/lib/api";

function TierBadge({ tier, isTrial, scanLimit }: { tier: string; isTrial: boolean; scanLimit: number }) {
  if (isTrial && scanLimit === 0) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
        <Ban className="h-3 w-3" />
        Deactivated
      </span>
    );
  }
  if (isTrial) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
        <Gift className="h-3 w-3" />
        Demo
      </span>
    );
  }
  const cls: Record<string, string> = {
    enterprise: "bg-violet-100 text-violet-700",
    pro: "bg-indigo-100 text-indigo-700",
    starter: "bg-emerald-100 text-emerald-700",
  };
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold capitalize", cls[tier] ?? "bg-slate-100 text-slate-600")}>
      {tier}
    </span>
  );
}

type Action = { type: "trial" | "tier"; orgId: string };

export default function AdminPage() {
  const { getToken } = useAuth();
  const [orgs, setOrgs] = useState<AdminOrg[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<Action | null>(null);

  // inline form state
  const [trialScans, setTrialScans] = useState<Record<string, number>>({});
  const [tierChoice, setTierChoice] = useState<Record<string, "starter" | "pro" | "enterprise">>({});

  const fetchOrgs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      if (!token) return;
      setOrgs(await adminListOrgs(token));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load orgs");
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => { fetchOrgs(); }, [fetchOrgs]);

  async function grantTrial(org: AdminOrg) {
    setAction({ type: "trial", orgId: org.id });
    try {
      const token = await getToken();
      if (!token) return;
      const scans = trialScans[org.id] ?? 20;
      await adminSetTrial(org.id, scans, token);
      await fetchOrgs();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to grant trial");
    } finally {
      setAction(null);
    }
  }

  async function revokeTrial(org: AdminOrg) {
    setAction({ type: "trial", orgId: org.id });
    try {
      const token = await getToken();
      if (!token) return;
      await adminRevokeTrial(org.id, token);
      await fetchOrgs();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to revoke trial");
    } finally {
      setAction(null);
    }
  }

  async function deactivate(org: AdminOrg) {
    if (!confirm(`Deactivate ${org.name}? They won't be able to run new scans.`)) return;
    setAction({ type: "trial", orgId: org.id });
    try {
      const token = await getToken();
      if (!token) return;
      await adminSetTrial(org.id, 0, token);
      await fetchOrgs();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to deactivate");
    } finally {
      setAction(null);
    }
  }

  async function grantFullAccess(org: AdminOrg) {
    setAction({ type: "tier", orgId: org.id });
    try {
      const token = await getToken();
      if (!token) return;
      const tier = tierChoice[org.id] ?? "starter";
      await adminSetTier(org.id, tier, token);
      await fetchOrgs();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to grant access");
    } finally {
      setAction(null);
    }
  }

  const busy = (orgId: string) => action?.orgId === orgId;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Admin — Organizations</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            All sign-ups start with 5 demo scans. Grant trial access or upgrade to a paid tier here.
          </p>
        </div>
        <button
          onClick={fetchOrgs}
          className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
          </div>
        ) : orgs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Building2 className="mb-3 h-8 w-8 text-slate-300" />
            <p className="text-sm text-slate-500">No organizations yet</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left">
                  {["Organization", "Status", "Scans Used / Limit", "Releases", "Joined", "Trial Access", "Full Access", ""].map((h) => (
                    <th key={h} className="px-5 py-3 text-xs font-medium uppercase tracking-wider text-slate-400 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {orgs.map((org) => {
                  const isBusy = busy(org.id);
                  const usagePct = org.scan_limit > 0
                    ? Math.min(100, Math.round((org.scan_count_current_period / org.scan_limit) * 100))
                    : 0;

                  return (
                    <tr key={org.id} className="hover:bg-slate-50/60">
                      {/* Org name */}
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-2">
                          <Building2 className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                          <span className="font-medium text-slate-800">{org.name}</span>
                        </div>
                        <p className="mt-0.5 font-mono text-[10px] text-slate-400">{org.clerk_org_id}</p>
                      </td>

                      {/* Tier / trial badge */}
                      <td className="px-5 py-3">
                        <TierBadge tier={org.tier} isTrial={org.is_trial} scanLimit={org.scan_limit} />
                      </td>

                      {/* Scan usage bar */}
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-2">
                          <span className="tabular-nums text-xs font-semibold text-slate-700">
                            {org.scan_count_current_period} / {org.scan_limit === -1 ? "∞" : org.scan_limit}
                          </span>
                          {org.scan_limit > 0 && (
                            <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
                              <div
                                className={cn(
                                  "h-full rounded-full",
                                  usagePct >= 90 ? "bg-red-500" : usagePct >= 70 ? "bg-amber-400" : "bg-emerald-400"
                                )}
                                style={{ width: `${usagePct}%` }}
                              />
                            </div>
                          )}
                        </div>
                      </td>

                      {/* Releases */}
                      <td className="px-5 py-3 tabular-nums text-xs text-slate-600">
                        {org.total_releases}
                      </td>

                      {/* Joined */}
                      <td className="px-5 py-3 text-xs text-slate-400 whitespace-nowrap">
                        {new Date(org.created_at).toLocaleDateString()}
                      </td>

                      {/* Trial access column */}
                      <td className="px-5 py-3">
                        {org.is_trial ? (
                          <div className="flex items-center gap-2">
                            <input
                              type="number"
                              min={1}
                              max={500}
                              value={trialScans[org.id] ?? (org.scan_limit > 0 ? org.scan_limit : 20)}
                              onChange={(e) => setTrialScans((p) => ({ ...p, [org.id]: Number(e.target.value) }))}
                              className="w-16 rounded border border-slate-200 px-1.5 py-0.5 text-xs tabular-nums text-slate-700 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                            />
                            <button
                              onClick={() => grantTrial(org)}
                              disabled={isBusy}
                              className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-indigo-600 hover:bg-indigo-50 disabled:opacity-50"
                            >
                              <ShieldCheck className="h-3 w-3" />
                              {isBusy && action?.type === "trial" ? "…" : "Update"}
                            </button>
                            <button
                              onClick={() => revokeTrial(org)}
                              disabled={isBusy}
                              className="rounded px-2 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100 disabled:opacity-50"
                            >
                              Revoke
                            </button>
                            <button
                              onClick={() => deactivate(org)}
                              disabled={isBusy}
                              className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                            >
                              <Ban className="h-3 w-3" />
                              Off
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2">
                            <input
                              type="number"
                              min={1}
                              max={500}
                              placeholder="20"
                              value={trialScans[org.id] ?? ""}
                              onChange={(e) => setTrialScans((p) => ({ ...p, [org.id]: Number(e.target.value) }))}
                              className="w-16 rounded border border-slate-200 px-1.5 py-0.5 text-xs tabular-nums text-slate-700 placeholder:text-slate-300 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                            />
                            <button
                              onClick={() => grantTrial(org)}
                              disabled={isBusy}
                              className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-amber-600 hover:bg-amber-50 disabled:opacity-50"
                            >
                              <Gift className="h-3 w-3" />
                              {isBusy && action?.type === "trial" ? "…" : "Grant Demo"}
                            </button>
                            <button
                              onClick={() => deactivate(org)}
                              disabled={isBusy}
                              className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                            >
                              <Ban className="h-3 w-3" />
                              Off
                            </button>
                          </div>
                        )}
                      </td>

                      {/* Full access column */}
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-2">
                          <select
                            value={tierChoice[org.id] ?? org.tier}
                            onChange={(e) => setTierChoice((p) => ({ ...p, [org.id]: e.target.value as "starter" | "pro" | "enterprise" }))}
                            className="rounded border border-slate-200 px-1.5 py-0.5 text-xs text-slate-700 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                          >
                            <option value="starter">Starter (50/mo)</option>
                            <option value="pro">Pro (500/mo)</option>
                            <option value="enterprise">Enterprise (∞)</option>
                          </select>
                          <button
                            onClick={() => grantFullAccess(org)}
                            disabled={isBusy}
                            className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                          >
                            <Unlock className="h-3 w-3" />
                            {isBusy && action?.type === "tier" ? "…" : "Activate"}
                          </button>
                        </div>
                      </td>

                      {/* Drill-in */}
                      <td className="px-5 py-3 text-right">
                        <Link
                          href={`/admin/orgs/${org.id}`}
                          className="flex items-center justify-end gap-0.5 text-xs font-medium text-indigo-600 hover:text-indigo-700 whitespace-nowrap"
                        >
                          View Scans <ChevronRight className="h-3.5 w-3.5" />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
