"use client";

import { useState } from "react";
import { useOrganizationList, useClerk } from "@clerk/nextjs";
import { Zap, Plus, ChevronRight, Loader2, ArrowLeft } from "lucide-react";
import { cn } from "@/lib/utils";

export default function OrgSelectionPage() {
  const clerk = useClerk();
  const { userMemberships, setActive, isLoaded } = useOrganizationList({
    userMemberships: { infinite: false },
  });

  const [creating, setCreating] = useState(false);
  const [workspaceName, setWorkspaceName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const memberships = userMemberships?.data ?? [];
  const hasOrgs = memberships.length > 0;

  async function selectOrg(orgId: string) {
    await setActive!({ organization: orgId });
    window.location.href = "/dashboard";
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!workspaceName.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const org = await clerk.createOrganization({ name: workspaceName.trim() });
      await setActive!({ organization: org.id });
      window.location.href = "/dashboard";
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Could not create workspace.";
      setError(msg);
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col items-center gap-6">
      {/* Header */}
      <div className="text-center">
        <div className="mb-3 flex items-center justify-center gap-2">
          <Zap className="h-5 w-5 text-indigo-600" />
          <span className="text-lg font-bold tracking-tight text-slate-900">
            SONGGATE
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-slate-900">
          {creating
            ? "Create your workspace"
            : hasOrgs
            ? "Select your organization"
            : "Create your workspace"}
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          {creating
            ? "Give your team workspace a name."
            : hasOrgs
            ? "Choose an existing workspace or create a new one to continue."
            : "Set up your team workspace to start validating releases."}
        </p>
      </div>

      {/* Body */}
      {!isLoaded ? (
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      ) : creating ? (
        /* ── Inline create form ── */
        <form onSubmit={handleCreate} className="w-full max-w-sm space-y-3">
          <div>
            <label
              htmlFor="workspace-name"
              className="mb-1.5 block text-sm font-medium text-slate-700"
            >
              Workspace name
            </label>
            <input
              id="workspace-name"
              type="text"
              autoFocus
              value={workspaceName}
              onChange={(e) => setWorkspaceName(e.target.value)}
              placeholder="e.g. Acme Distribution"
              className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
            />
          </div>

          {error && (
            <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting || !workspaceName.trim()}
            className={cn(
              "flex w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-sm font-semibold transition-colors",
              submitting || !workspaceName.trim()
                ? "bg-slate-100 text-slate-400 cursor-not-allowed"
                : "bg-indigo-600 text-white hover:bg-indigo-700"
            )}
          >
            {submitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Creating…
              </>
            ) : (
              "Create workspace"
            )}
          </button>

          {hasOrgs && (
            <button
              type="button"
              onClick={() => { setCreating(false); setError(null); }}
              className="flex w-full items-center justify-center gap-1.5 text-sm text-slate-500 hover:text-slate-700"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to organizations
            </button>
          )}
        </form>
      ) : (
        /* ── Org list ── */
        <div className="w-full max-w-sm space-y-3">
          {memberships.map(({ organization }) => (
            <button
              key={organization.id}
              onClick={() => selectOrg(organization.id)}
              className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-4 py-3 text-left text-sm font-medium text-slate-800 transition-colors hover:border-indigo-300 hover:bg-indigo-50"
            >
              <span>{organization.name}</span>
              <ChevronRight className="h-4 w-4 text-slate-400" />
            </button>
          ))}

          <button
            onClick={() => setCreating(true)}
            className={cn(
              "flex w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-sm font-semibold transition-colors",
              hasOrgs
                ? "border border-dashed border-slate-300 text-slate-600 hover:border-indigo-400 hover:bg-indigo-50 hover:text-indigo-700"
                : "bg-indigo-600 text-white hover:bg-indigo-700"
            )}
          >
            <Plus className="h-4 w-4" />
            Create your workspace
          </button>
        </div>
      )}
    </div>
  );
}
