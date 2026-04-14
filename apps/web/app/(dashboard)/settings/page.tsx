"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { Key, Plus, Trash2, Copy, Check, Loader2, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface APIKeyRow {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

interface CreatedKey extends APIKeyRow {
  key: string;
}

function fmt(iso: string | null) {
  if (!iso) return "Never";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function SettingsPage() {
  const { getToken } = useAuth();
  const [keys, setKeys] = useState<APIKeyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [newKey, setNewKey] = useState<CreatedKey | null>(null);
  const [copied, setCopied] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [planError, setPlanError] = useState(false);

  async function loadKeys() {
    const token = await getToken();
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/billing/api-keys`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) setKeys(await res.json());
    } catch {
      // non-fatal
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadKeys(); }, []); // eslint-disable-line

  async function createKey() {
    if (!newName.trim()) return;
    setCreating(true);
    setError(null);
    setPlanError(false);
    try {
      const token = await getToken();
      const res = await fetch(`${API_BASE}/billing/api-keys`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ name: newName.trim() }),
      });
      if (res.status === 403) {
        setPlanError(true);
        return;
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail ?? "Failed to create key.");
        return;
      }
      const created: CreatedKey = await res.json();
      setNewKey(created);
      setKeys((prev) => [created, ...prev]);
      setNewName("");
      setShowCreate(false);
    } catch {
      setError("Network error — please try again.");
    } finally {
      setCreating(false);
    }
  }

  async function revokeKey(id: string) {
    setRevoking(id);
    try {
      const token = await getToken();
      await fetch(`${API_BASE}/billing/api-keys/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      setKeys((prev) => prev.filter((k) => k.id !== id));
    } finally {
      setRevoking(null);
    }
  }

  function copyKey() {
    if (!newKey) return;
    navigator.clipboard.writeText(newKey.key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const [notifEmail, setNotifEmail] = useState("");
  const [notifSaving, setNotifSaving] = useState(false);
  const [notifSaved, setNotifSaved] = useState(false);

  async function saveNotifEmail() {
    setNotifSaving(true);
    try {
      const token = await getToken();
      await fetch(`${API_BASE}/settings/notification-email`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email: notifEmail }),
      });
      setNotifSaved(true);
      setTimeout(() => setNotifSaved(false), 3000);
    } finally {
      setNotifSaving(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Settings</h1>
        <p className="mt-1 text-sm text-slate-500">
          API keys and notification configuration.
        </p>
      </div>

      {/* Notifications */}
      <div className="rounded-lg border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-6 py-4">
          <h2 className="font-medium text-slate-900">Notifications</h2>
          <p className="mt-0.5 text-xs text-slate-400">Receive an email when each scan completes or fails.</p>
        </div>
        <div className="px-6 py-5">
          <label className="mb-1.5 block text-xs font-medium text-slate-600">
            Notification email
          </label>
          <div className="flex items-center gap-2">
            <input
              type="email"
              value={notifEmail}
              onChange={(e) => setNotifEmail(e.target.value)}
              placeholder="you@yourcompany.com"
              className="w-72 rounded-md border border-slate-200 px-3 py-1.5 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
            />
            <button
              onClick={saveNotifEmail}
              disabled={notifSaving || !notifEmail}
              className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 hover:bg-indigo-700"
            >
              {notifSaved ? <><Check className="h-3.5 w-3.5" /> Saved</> : notifSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save"}
            </button>
          </div>
        </div>
      </div>

      {/* API Keys section */}
      <div className="rounded-lg border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <div className="flex items-center gap-2">
            <Key className="h-4 w-4 text-slate-500" />
            <h2 className="font-medium text-slate-900">API Keys</h2>
          </div>
          <button
            onClick={() => { setShowCreate(true); setNewKey(null); setError(null); setPlanError(false); }}
            className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
          >
            <Plus className="h-3.5 w-3.5" />
            New key
          </button>
        </div>

        {/* New key revealed */}
        {newKey && (
          <div className="border-b border-emerald-100 bg-emerald-50 px-6 py-4">
            <p className="mb-2 text-sm font-medium text-emerald-800">
              Key created — copy it now. You won't see it again.
            </p>
            <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-white px-3 py-2 font-mono text-xs">
              <span className="flex-1 select-all break-all text-slate-700">{newKey.key}</span>
              <button
                onClick={copyKey}
                className="shrink-0 rounded p-1 text-slate-400 hover:text-slate-600"
              >
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
            </div>
            <button
              onClick={() => setNewKey(null)}
              className="mt-2 text-xs text-emerald-700 underline"
            >
              I've saved it
            </button>
          </div>
        )}

        {/* Create form */}
        {showCreate && (
          <div className="border-b border-slate-100 px-6 py-4">
            {planError && (
              <div className="mb-3 flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                API keys require Professional or Enterprise plan.{" "}
                <a href="/billing" className="font-medium underline">Upgrade →</a>
              </div>
            )}
            {error && (
              <p className="mb-3 text-sm text-red-600">{error}</p>
            )}
            <div className="flex items-center gap-2">
              <input
                type="text"
                placeholder="Key name (e.g. Production pipeline)"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && createKey()}
                className="flex-1 rounded-md border border-slate-200 px-3 py-1.5 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
              />
              <button
                onClick={createKey}
                disabled={creating || !newName.trim()}
                className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-indigo-700"
              >
                {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Create"}
              </button>
              <button
                onClick={() => { setShowCreate(false); setError(null); setPlanError(false); }}
                className="text-sm text-slate-500 hover:text-slate-700"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Key list */}
        <div className="divide-y divide-slate-100">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-slate-300" />
            </div>
          ) : keys.length === 0 ? (
            <div className="py-8 text-center text-sm text-slate-400">
              No API keys yet. Create one to start using the public API.
            </div>
          ) : (
            keys.map((k) => (
              <div key={k.id} className="flex items-center gap-4 px-6 py-3">
                <Key className="h-4 w-4 shrink-0 text-slate-300" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-800 text-sm">{k.name}</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-3 text-xs text-slate-400">
                    <span className="font-mono">{k.key_prefix}…</span>
                    <span>Created {fmt(k.created_at)}</span>
                    <span>Last used {fmt(k.last_used_at)}</span>
                  </div>
                </div>
                <button
                  onClick={() => revokeKey(k.id)}
                  disabled={revoking === k.id}
                  className="shrink-0 rounded-md p-1.5 text-slate-300 hover:bg-red-50 hover:text-red-500 disabled:opacity-50"
                  title="Revoke key"
                >
                  {revoking === k.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
