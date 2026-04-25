"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { Webhook, Plus, Trash2, Loader2, CheckCircle2, AlertTriangle, ChevronDown, ChevronUp, Send } from "lucide-react";
import { cn } from "@/lib/utils";

interface WebhookEndpoint {
  id: string;
  url: string;
  description: string | null;
  events: string[] | null;
  active: boolean;
  created_at: string;
}

interface WebhookDelivery {
  id: string;
  event_type: string;
  status_code: number | null;
  status: string;
  attempt: number;
  error: string | null;
  delivered_at: string | null;
  created_at: string;
}

const ALL_EVENTS = ["scan.complete", "scan.failed", "bulk.complete", "test.ping"];

export default function WebhooksSettingsPage() {
  const { getToken } = useAuth();
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(true);
  const [endpoints, setEndpoints] = useState<WebhookEndpoint[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // New endpoint form
  const [showForm, setShowForm] = useState(false);
  const [newUrl, setNewUrl] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newEvents, setNewEvents] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);

  // Delivery log
  const [openDeliveries, setOpenDeliveries] = useState<string | null>(null);
  const [deliveries, setDeliveries] = useState<Record<string, WebhookDelivery[]>>({});
  const [deliveryLoading, setDeliveryLoading] = useState(false);

  const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  useEffect(() => {
    getToken().then((t) => {
      if (t) {
        setToken(t);
        fetchEndpoints(t);
      }
    });
  }, [getToken]);

  async function fetchEndpoints(tok: string) {
    setLoading(true);
    try {
      const res = await fetch(`${API}/settings/webhooks`, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      if (!res.ok) throw new Error("Failed to load webhook endpoints");
      setEndpoints(await res.json());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function createEndpoint() {
    if (!newUrl) return;
    setCreating(true);
    setError(null);
    try {
      const res = await fetch(`${API}/settings/webhooks`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          url: newUrl,
          description: newDesc || null,
          events: newEvents.length ? newEvents : null,
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail ?? "Failed to create webhook");
      }
      const data = await res.json();
      setCreatedSecret(data.secret);
      setShowForm(false);
      setNewUrl("");
      setNewDesc("");
      setNewEvents([]);
      await fetchEndpoints(token);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  }

  async function deleteEndpoint(id: string) {
    if (!confirm("Delete this webhook endpoint?")) return;
    try {
      await fetch(`${API}/settings/webhooks/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      setEndpoints((prev) => prev.filter((e) => e.id !== id));
    } catch {
      setError("Failed to delete endpoint");
    }
  }

  async function testEndpoint(id: string) {
    try {
      await fetch(`${API}/settings/webhooks/${id}/test`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      setSuccess("Test event sent");
      setTimeout(() => setSuccess(null), 3000);
    } catch {
      setError("Failed to send test event");
    }
  }

  async function loadDeliveries(id: string) {
    if (openDeliveries === id) {
      setOpenDeliveries(null);
      return;
    }
    setOpenDeliveries(id);
    if (deliveries[id]) return;
    setDeliveryLoading(true);
    try {
      const res = await fetch(`${API}/settings/webhooks/${id}/deliveries`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setDeliveries((prev) => ({ ...prev, [id]: data }));
    } finally {
      setDeliveryLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    );
  }

  return (
    <div className="space-y-8 max-w-3xl">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 flex items-center gap-2">
            <Webhook className="h-6 w-6 text-indigo-600" />
            Webhook Endpoints
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Register HTTPS endpoints to receive real-time scan events.
            All deliveries are signed with HMAC-SHA256.
          </p>
        </div>
        <button
          onClick={() => { setShowForm(!showForm); setCreatedSecret(null); }}
          className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          <Plus className="h-4 w-4" />
          Add endpoint
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      )}
      {success && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4" /> {success}
        </div>
      )}

      {/* Created secret notice */}
      {createdSecret && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-5 space-y-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0" />
            <p className="text-sm font-semibold text-amber-800">Save your signing secret now — it won&apos;t be shown again.</p>
          </div>
          <pre className="rounded-lg bg-amber-900/10 px-4 py-3 font-mono text-sm text-amber-900 break-all select-all">
            {createdSecret}
          </pre>
          <p className="text-xs text-amber-700">
            Use this secret to verify the <code>X-SONGGATE-Signature</code> header on incoming deliveries.
          </p>
          <button onClick={() => setCreatedSecret(null)} className="text-xs font-medium text-amber-700 underline">
            I&apos;ve saved this secret
          </button>
        </div>
      )}

      {/* Add endpoint form */}
      {showForm && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-5 space-y-4">
          <h3 className="text-sm font-semibold text-slate-800">Register new endpoint</h3>
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">URL <span className="text-red-500">*</span></label>
              <input
                type="url"
                placeholder="https://your-app.com/hooks/songgate"
                value={newUrl}
                onChange={(e) => setNewUrl(e.target.value)}
                className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Description</label>
              <input
                type="text"
                placeholder="Production webhook"
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-2">Events (leave blank for all)</label>
              <div className="flex flex-wrap gap-2">
                {ALL_EVENTS.map((ev) => (
                  <label key={ev} className="flex items-center gap-1.5 text-xs cursor-pointer">
                    <input
                      type="checkbox"
                      checked={newEvents.includes(ev)}
                      onChange={(e) =>
                        setNewEvents((prev) =>
                          e.target.checked ? [...prev, ev] : prev.filter((x) => x !== ev)
                        )
                      }
                    />
                    <span className="font-mono text-slate-700">{ev}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3 pt-1">
            <button
              onClick={createEndpoint}
              disabled={!newUrl || creating}
              className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
            >
              {creating && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Create endpoint
            </button>
            <button onClick={() => setShowForm(false)} className="text-sm text-slate-500 hover:text-slate-700">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Endpoints list */}
      {endpoints.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-6 py-12 text-center">
          <Webhook className="mx-auto h-8 w-8 text-slate-300 mb-3" />
          <p className="text-sm text-slate-500">No webhook endpoints yet.</p>
          <p className="text-xs text-slate-400 mt-1">Add an endpoint to start receiving scan events.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {endpoints.map((ep) => (
            <div key={ep.id} className="rounded-xl border border-slate-200 bg-white shadow-sm">
              <div className="flex items-start gap-3 p-4">
                <div className="mt-0.5 h-2 w-2 rounded-full bg-emerald-400 shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="font-mono text-sm font-medium text-slate-800 truncate">{ep.url}</p>
                  {ep.description && <p className="text-xs text-slate-400 mt-0.5">{ep.description}</p>}
                  <div className="mt-2 flex flex-wrap gap-1">
                    {(ep.events ?? ALL_EVENTS).map((ev) => (
                      <span key={ev} className="rounded-full bg-indigo-50 border border-indigo-100 px-2 py-0.5 text-xs font-mono text-indigo-700">
                        {ev}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => testEndpoint(ep.id)}
                    className="flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                    title="Send test event"
                  >
                    <Send className="h-3 w-3" /> Test
                  </button>
                  <button
                    onClick={() => loadDeliveries(ep.id)}
                    className="flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                  >
                    Deliveries
                    {openDeliveries === ep.id
                      ? <ChevronUp className="h-3 w-3" />
                      : <ChevronDown className="h-3 w-3" />}
                  </button>
                  <button
                    onClick={() => deleteEndpoint(ep.id)}
                    className="flex items-center justify-center h-7 w-7 rounded-md border border-red-200 text-red-500 hover:bg-red-50"
                    title="Delete endpoint"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              {/* Delivery log */}
              {openDeliveries === ep.id && (
                <div className="border-t border-slate-100 bg-slate-50 px-4 py-3 space-y-2">
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Recent deliveries</p>
                  {deliveryLoading ? (
                    <div className="flex justify-center py-4">
                      <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
                    </div>
                  ) : (deliveries[ep.id] ?? []).length === 0 ? (
                    <p className="text-xs text-slate-400 py-2">No deliveries yet.</p>
                  ) : (
                    (deliveries[ep.id] ?? []).map((d) => (
                      <div key={d.id} className={cn(
                        "flex items-start gap-3 rounded-md border px-3 py-2 text-xs",
                        d.status === "delivered" ? "border-emerald-100 bg-emerald-50" : "border-red-100 bg-red-50",
                      )}>
                        {d.status === "delivered"
                          ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0 mt-0.5" />
                          : <AlertTriangle className="h-3.5 w-3.5 text-red-500 shrink-0 mt-0.5" />}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-mono font-semibold text-slate-700">{d.event_type}</span>
                            {d.status_code && (
                              <span className={cn(
                                "rounded px-1.5 py-0.5 font-mono font-semibold",
                                d.status_code < 300 ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700",
                              )}>
                                {d.status_code}
                              </span>
                            )}
                          </div>
                          {d.error && <p className="mt-0.5 text-red-600 truncate">{d.error}</p>}
                          <p className="mt-0.5 text-slate-400">{d.created_at ? new Date(d.created_at).toLocaleString() : ""}</p>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Verification guide */}
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-5 space-y-3">
        <h3 className="text-sm font-semibold text-slate-800">Verifying signatures</h3>
        <p className="text-xs text-slate-500 leading-relaxed">
          Every delivery includes an <code className="rounded bg-white border border-slate-200 px-1 font-mono">X-SONGGATE-Signature</code> header.
          Compute <code className="rounded bg-white border border-slate-200 px-1 font-mono">sha256=HMAC(secret, body)</code> and compare with the header using a constant-time comparison.
        </p>
        <pre className="rounded-lg bg-slate-900 px-4 py-3 font-mono text-xs text-slate-100 overflow-x-auto">{`import hashlib, hmac

def verify(secret: str, body: bytes, header: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header)`}</pre>
      </div>
    </div>
  );
}
